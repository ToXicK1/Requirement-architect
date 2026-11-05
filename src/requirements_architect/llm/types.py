"""Provider-independent request/response types and error taxonomy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """A single completion request. `model` is resolved by the gateway when empty."""

    messages: list[Message] = Field(min_length=1)
    system: str | None = None
    model: str | None = None
    max_tokens: int = Field(default=4096, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    prompt_id: str = "adhoc"
    prompt_version: str = "0"
    project_id: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    usage: Usage = Field(default_factory=Usage)


class LLMError(Exception):
    """Base error. Messages must never contain credentials or provider response bodies."""


class LLMConfigError(LLMError):
    """Invalid or missing gateway configuration."""


class LLMTransientError(LLMError):
    """Retryable failure (5xx, network)."""


class LLMTimeoutError(LLMTransientError):
    """The call exceeded its deadline."""


class LLMRateLimitError(LLMTransientError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMPermanentError(LLMError):
    """Non-retryable failure (auth, bad request, unknown model)."""


class LLMStructuredOutputError(LLMError):
    """Model output could not be validated against the requested schema."""
