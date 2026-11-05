import json

import httpx
import pytest
from pydantic import SecretStr

from requirements_architect.llm.providers.anthropic import AnthropicProvider
from requirements_architect.llm.providers.openai_compat import OpenAICompatProvider
from requirements_architect.llm.types import (
    LLMPermanentError,
    LLMRateLimitError,
    LLMRequest,
    LLMTimeoutError,
    LLMTransientError,
    Message,
)

KEY = SecretStr("sk-very-secret")
REQ = LLMRequest(messages=[Message(role="user", content="hello")], system="be brief", max_tokens=50)


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_anthropic_request_and_response_mapping():
    seen = {}

    def h(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "hi "}, {"type": "text", "text": "there"}],
                "usage": {"input_tokens": 11, "output_tokens": 3},
            },
        )

    r = await AnthropicProvider(KEY, client(h)).complete(REQ, "model-x")
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-very-secret"
    assert seen["headers"]["anthropic-version"]
    assert seen["body"]["system"] == "be brief" and seen["body"]["model"] == "model-x"
    assert r.text == "hi there" and (r.usage.input_tokens, r.usage.output_tokens) == (11, 3)


async def test_openai_compat_request_and_response_mapping():
    seen = {}

    def h(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "yo"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    p = OpenAICompatProvider(KEY, client(h), base_url="https://gw.example/v1/")
    r = await p.complete(REQ, "m")
    assert seen["url"] == "https://gw.example/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-very-secret"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "be brief"}
    assert r.text == "yo" and r.usage.output_tokens == 2


@pytest.mark.parametrize("cls", [AnthropicProvider, OpenAICompatProvider])
@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (429, LLMRateLimitError),
        (500, LLMTransientError),
        (529, LLMTransientError),
        (401, LLMPermanentError),
        (400, LLMPermanentError),
        (404, LLMPermanentError),
    ],
)
async def test_status_mapping_and_no_secret_or_body_leak(cls, status, exc):
    def h(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, text="BODY-WITH-SK sk-very-secret", headers={"retry-after": "4"}
        )

    with pytest.raises(exc) as ei:
        await cls(KEY, client(h)).complete(REQ, "m")
    assert "sk-very-secret" not in str(ei.value) and "BODY-WITH-SK" not in str(ei.value)
    if status == 429:
        assert ei.value.retry_after == 4.0


@pytest.mark.parametrize("cls", [AnthropicProvider, OpenAICompatProvider])
async def test_timeout_and_network_errors_are_mapped(cls):
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def netfail(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(LLMTimeoutError):
        await cls(KEY, client(timeout)).complete(REQ, "m")
    with pytest.raises(LLMTransientError):
        await cls(KEY, client(netfail)).complete(REQ, "m")


@pytest.mark.parametrize("cls", [AnthropicProvider, OpenAICompatProvider])
async def test_malformed_payloads_are_transient(cls):
    for resp in (httpx.Response(200, text="<html>"), httpx.Response(200, json={"unexpected": 1})):
        with pytest.raises(LLMTransientError):
            await cls(KEY, client(lambda _, r=resp: r)).complete(REQ, "m")
