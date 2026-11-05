"""Test-only fake provider. Must never be imported from src/."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from requirements_architect.llm.types import LLMRequest, LLMResponse, Usage

Step = str | Exception | Callable[[LLMRequest], str]


class FakeProvider:
    def __init__(self, steps: list[Step], name: str = "fake", delay: float = 0.0) -> None:
        self.name = name
        self._steps = list(steps)
        self._delay = delay
        self.calls: list[LLMRequest] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        self.calls.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            step = self._steps.pop(0) if len(self._steps) > 1 else self._steps[0]
            if isinstance(step, Exception):
                raise step
            text = step(request) if callable(step) else step
            return LLMResponse(
                text=text,
                provider=self.name,
                model=model,
                usage=Usage(input_tokens=1000, output_tokens=500),
            )
        finally:
            self.in_flight -= 1


class FakeSearch:
    """Test-only SearchProvider: returns canned hits, or raises, per call."""

    def __init__(self, name: str, hits=None, error: Exception | None = None) -> None:
        self.name, self._hits, self._error = name, hits or [], error
        self.queries: list[str] = []

    async def search(self, query: str, limit: int):
        self.queries.append(query)
        if self._error:
            raise self._error
        return list(self._hits)[:limit]
