"""LLM gateway: timeouts, bounded retries with backoff, rate-limit handling,
controlled fallbacks, structured output validation, and usage/cost tracking."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import structlog
from pydantic import BaseModel, ValidationError

from requirements_architect.llm.pricing import PriceTable, estimate_cost
from requirements_architect.llm.provider import LLMProvider
from requirements_architect.llm.types import (
    LLMConfigError,
    LLMError,
    LLMPermanentError,
    LLMRequest,
    LLMResponse,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMTransientError,
    Message,
)
from requirements_architect.llm.usage import UsageRecord, UsageTracker

log = structlog.get_logger()

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

JSON_INSTRUCTION = (
    "Respond with a single JSON object that conforms to this JSON Schema and nothing else. "
    "No prose, no markdown fences.\nSCHEMA:\n"
)


@dataclass(frozen=True)
class Target:
    """A provider plus the model to use on it."""

    provider: LLMProvider
    model: str


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3  # per target, including the first try
    base_delay: float = 1.0
    max_delay: float = 30.0
    timeout: float = 60.0
    structured_attempts: int = 2  # re-asks when output fails schema validation


def parse_json_object(text: str) -> object:
    cleaned = _FENCE.sub("", text.strip()).strip()
    return json.loads(cleaned)


class LLMGateway:
    def __init__(
        self,
        primary: Target,
        fallbacks: Sequence[Target] = (),
        *,
        policy: RetryPolicy | None = None,
        prices: PriceTable | None = None,
        tracker: UsageTracker | None = None,
        max_concurrency: int = 4,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_concurrency < 1:
            raise LLMConfigError("max_concurrency must be >= 1")
        self._targets = [primary, *fallbacks]
        self._policy = policy or RetryPolicy()
        self._prices = prices or {}
        self.tracker = tracker or UsageTracker()
        self._sem = asyncio.Semaphore(max_concurrency)
        self._sleep = sleep

    def _delay(self, attempt: int, exc: LLMTransientError) -> float:
        backoff = min(self._policy.max_delay, self._policy.base_delay * (2 ** (attempt - 1)))
        retry_after = getattr(exc, "retry_after", None)
        if isinstance(retry_after, (int, float)):
            return float(min(self._policy.max_delay, max(backoff, retry_after)))
        return float(backoff)

    async def _call_once(self, target: Target, request: LLMRequest, attempt: int) -> LLMResponse:
        model = request.model or target.model
        start = time.monotonic()
        try:
            async with self._sem:
                resp = await asyncio.wait_for(
                    target.provider.complete(request, model), timeout=self._policy.timeout
                )
        except TimeoutError as exc:
            await self._record(target, model, request, start, attempt, None, "LLMTimeoutError")
            raise LLMTimeoutError(f"{target.provider.name}: deadline exceeded") from exc
        except LLMError as exc:
            await self._record(target, model, request, start, attempt, None, type(exc).__name__)
            raise
        await self._record(target, model, request, start, attempt, resp, None)
        return resp

    async def _record(
        self,
        target: Target,
        model: str,
        request: LLMRequest,
        start: float,
        attempt: int,
        resp: LLMResponse | None,
        error_type: str | None,
    ) -> None:
        usage = resp.usage if resp else None
        await self.tracker.record(
            UsageRecord(
                provider=target.provider.name,
                model=model,
                prompt_id=request.prompt_id,
                prompt_version=request.prompt_version,
                project_id=request.project_id,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                estimated_cost_usd=estimate_cost(model, usage, self._prices) if usage else None,
                latency_seconds=time.monotonic() - start,
                success=resp is not None,
                error_type=error_type,
                attempt=attempt,
            )
        )
        log.info(
            "llm_call",
            provider=target.provider.name,
            model=model,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            attempt=attempt,
            success=resp is not None,
            error_type=error_type,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        last: LLMTransientError | None = None
        for target in self._targets:
            for attempt in range(1, self._policy.max_attempts + 1):
                try:
                    return await self._call_once(target, request, attempt)
                except LLMPermanentError:
                    raise  # auth/bad request: retrying or switching vendors would mask a bug
                except LLMTransientError as exc:
                    last = exc
                    if attempt < self._policy.max_attempts:
                        await self._sleep(self._delay(attempt, exc))
            log.warning("llm_target_exhausted", provider=target.provider.name)
        raise LLMTransientError(
            f"all {len(self._targets)} configured target(s) failed; last error: {last}"
        ) from last

    async def complete_structured[T: BaseModel](
        self, request: LLMRequest, schema: type[T]
    ) -> tuple[T, LLMResponse]:
        """Complete and validate against a Pydantic model, re-asking with the validation error."""
        schema_json = json.dumps(schema.model_json_schema())
        system = (
            (request.system + "\n\n" if request.system else "") + JSON_INSTRUCTION + schema_json
        )
        messages = list(request.messages)
        last_error = ""
        for _ in range(self._policy.structured_attempts):
            req = request.model_copy(update={"system": system, "messages": messages})
            resp = await self.complete(req)
            try:
                return schema.model_validate(parse_json_object(resp.text)), resp
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = type(exc).__name__
                feedback = (
                    "Your previous reply was not valid for the schema "
                    f"({last_error}). Reply again with only the corrected JSON object."
                )
                messages = [
                    *request.messages,
                    Message(role="assistant", content=resp.text),
                    Message(role="user", content=feedback),
                ]
        raise LLMStructuredOutputError(
            f"output failed {schema.__name__} validation after "
            f"{self._policy.structured_attempts} attempt(s) ({last_error})"
        )
