"""Anthropic Messages API adapter."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from requirements_architect.llm.providers._http import post_json
from requirements_architect.llm.types import LLMRequest, LLMResponse, LLMTransientError, Usage

DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: SecretStr,
        client: httpx.AsyncClient,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
    ) -> None:
        self._key = api_key
        self._client = client
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        payload: dict[str, object] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.system:
            payload["system"] = request.system
        headers = {
            "x-api-key": self._key.get_secret_value(),
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        data = await post_json(
            self._client, self.name, f"{self._base}/v1/messages", headers, payload, self._timeout
        )
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise LLMTransientError("anthropic: response missing content")
        text = "".join(
            b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str)
        )
        usage_raw = data.get("usage")
        usage = Usage()
        if isinstance(usage_raw, dict):
            usage = Usage(
                input_tokens=int(usage_raw.get("input_tokens", 0) or 0),
                output_tokens=int(usage_raw.get("output_tokens", 0) or 0),
            )
        return LLMResponse(text=text, provider=self.name, model=model, usage=usage)
