"""OpenAI-compatible Chat Completions adapter (OpenAI, and gateways exposing the same schema)."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from requirements_architect.llm.providers._http import post_json
from requirements_architect.llm.types import LLMRequest, LLMResponse, LLMTransientError, Usage

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatProvider:
    name = "openai_compat"

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
        msgs: list[dict[str, str]] = []
        if request.system:
            msgs.append({"role": "system", "content": request.system})
        msgs.extend(m.model_dump() for m in request.messages)
        payload: dict[str, object] = {
            "model": model,
            "messages": msgs,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        headers = {
            "authorization": f"Bearer {self._key.get_secret_value()}",
            "content-type": "application/json",
        }
        data = await post_json(
            self._client,
            self.name,
            f"{self._base}/chat/completions",
            headers,
            payload,
            self._timeout,
        )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LLMTransientError("openai_compat: response missing choices")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise LLMTransientError("openai_compat: response missing content")
        usage_raw = data.get("usage")
        usage = Usage()
        if isinstance(usage_raw, dict):
            usage = Usage(
                input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
            )
        return LLMResponse(text=content, provider=self.name, model=model, usage=usage)
