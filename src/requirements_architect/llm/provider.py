"""Provider interface. Agent logic depends only on this, never on a vendor SDK."""

from __future__ import annotations

from typing import Protocol

from requirements_architect.llm.types import LLMRequest, LLMResponse


class LLMProvider(Protocol):
    name: str

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse: ...
