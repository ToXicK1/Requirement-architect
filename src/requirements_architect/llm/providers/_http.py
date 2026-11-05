"""Shared HTTP error mapping. Never echoes response bodies (may contain sensitive data)."""

from __future__ import annotations

import httpx

from requirements_architect.llm.types import (
    LLMError,
    LLMPermanentError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransientError,
)


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def raise_for_status(provider: str, resp: httpx.Response) -> None:
    code = resp.status_code
    if code < 400:
        return
    if code == 429:
        raise LLMRateLimitError(f"{provider}: rate limited (429)", _retry_after(resp))
    if code in (408, 409, 425) or code >= 500:
        raise LLMTransientError(f"{provider}: transient HTTP {code}")
    raise LLMPermanentError(f"{provider}: HTTP {code}")


async def post_json(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout: float,
) -> dict[str, object]:
    try:
        resp = await client.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise LLMTimeoutError(f"{provider}: request timed out") from exc
    except httpx.TransportError as exc:
        raise LLMTransientError(f"{provider}: network error ({type(exc).__name__})") from exc
    raise_for_status(provider, resp)
    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMTransientError(f"{provider}: malformed JSON response") from exc
    if not isinstance(data, dict):
        raise LLMError(f"{provider}: unexpected response shape")
    return data
