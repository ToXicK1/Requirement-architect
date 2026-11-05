"""Build an LLMGateway from validated settings."""

from __future__ import annotations

import json

import httpx
from pydantic import SecretStr, ValidationError

from requirements_architect.core.config import Settings
from requirements_architect.llm.gateway import LLMGateway, RetryPolicy, Target
from requirements_architect.llm.pricing import ModelPrice, PriceTable
from requirements_architect.llm.provider import LLMProvider
from requirements_architect.llm.providers.anthropic import DEFAULT_BASE_URL as ANTHROPIC_URL
from requirements_architect.llm.providers.anthropic import AnthropicProvider
from requirements_architect.llm.providers.openai_compat import DEFAULT_BASE_URL as OPENAI_URL
from requirements_architect.llm.providers.openai_compat import OpenAICompatProvider
from requirements_architect.llm.types import LLMConfigError


def _provider(
    kind: str, key: SecretStr, base_url: str | None, client: httpx.AsyncClient, timeout: float
) -> LLMProvider:
    if kind == "anthropic":
        return AnthropicProvider(key, client, base_url or ANTHROPIC_URL, timeout)
    if kind == "openai_compat":
        return OpenAICompatProvider(key, client, base_url or OPENAI_URL, timeout)
    raise LLMConfigError(f"unknown LLM provider: {kind}")


def parse_price_table(raw: str) -> PriceTable:
    try:
        data = json.loads(raw)
        return {k: ModelPrice.model_validate(v) for k, v in data.items()}
    except (json.JSONDecodeError, ValidationError, AttributeError) as exc:
        raise LLMConfigError("LLM_PRICE_TABLE_JSON is invalid") from exc


def build_gateway(settings: Settings, client: httpx.AsyncClient) -> LLMGateway:
    if not settings.llm_configured or settings.llm_provider is None:
        raise LLMConfigError("LLM is not configured (set LLM_PROVIDER, LLM_API_KEY, LLM_MODEL)")
    t = settings.llm_timeout_seconds
    primary = Target(
        _provider(settings.llm_provider, settings.llm_api_key, settings.llm_base_url, client, t),
        settings.llm_model,
    )
    fallbacks: list[Target] = []
    if settings.llm_fallback_provider:
        fallbacks.append(
            Target(
                _provider(
                    settings.llm_fallback_provider,
                    settings.llm_fallback_api_key,
                    settings.llm_fallback_base_url,
                    client,
                    t,
                ),
                settings.llm_fallback_model,
            )
        )
    return LLMGateway(
        primary,
        fallbacks,
        policy=RetryPolicy(max_attempts=settings.llm_max_attempts, timeout=t),
        prices=parse_price_table(settings.llm_price_table_json),
        max_concurrency=settings.llm_max_concurrency,
    )
