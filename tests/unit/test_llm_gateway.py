import asyncio
from decimal import Decimal

import pytest
from pydantic import BaseModel

from requirements_architect.llm.gateway import LLMGateway, RetryPolicy, Target
from requirements_architect.llm.pricing import ModelPrice
from requirements_architect.llm.types import (
    LLMPermanentError,
    LLMRateLimitError,
    LLMRequest,
    LLMStructuredOutputError,
    LLMTransientError,
    Message,
)
from tests.fakes import FakeProvider

PRICES = {"m1": ModelPrice(input_per_mtok=Decimal(2), output_per_mtok=Decimal(10))}


def req(**kw):
    return LLMRequest(
        messages=[Message(role="user", content="hi")], prompt_id="p", prompt_version="3", **kw
    )


class Sleeper:
    def __init__(self):
        self.delays: list[float] = []

    async def __call__(self, d: float) -> None:
        self.delays.append(d)


def gw(primary, fallbacks=(), sleeper=None, **policy):
    return LLMGateway(
        Target(primary, "m1"),
        [Target(f, "m2") for f in fallbacks],
        policy=RetryPolicy(**{"max_attempts": 3, "base_delay": 1.0, **policy}),
        prices=PRICES,
        sleep=sleeper or Sleeper(),
    )


async def test_success_records_usage_cost_and_prompt_version():
    g = gw(FakeProvider(["ok"]))
    r = await g.complete(req())
    assert r.text == "ok"
    rec = g.tracker.records[0]
    assert (rec.prompt_id, rec.prompt_version, rec.model) == ("p", "3", "m1")
    assert rec.estimated_cost_usd == Decimal("0.007")  # 1000*2/1e6 + 500*10/1e6
    assert g.tracker.total_tokens() == (1000, 500)


async def test_unknown_model_cost_is_none_not_fabricated():
    g = LLMGateway(Target(FakeProvider(["ok"]), "unpriced"), sleep=Sleeper())
    await g.complete(req())
    assert g.tracker.records[0].estimated_cost_usd is None
    assert g.tracker.unpriced_calls() == 1 and g.tracker.total_cost_usd() == 0


async def test_retries_transient_with_exponential_backoff():
    s = Sleeper()
    p = FakeProvider([LLMTransientError("x"), LLMTransientError("x"), "ok"])
    r = await gw(p, sleeper=s).complete(req())
    assert r.text == "ok" and len(p.calls) == 3 and s.delays == [1.0, 2.0]


async def test_rate_limit_retry_after_respected_and_capped():
    s = Sleeper()
    p = FakeProvider([LLMRateLimitError("rl", retry_after=7), LLMRateLimitError("rl", 999), "ok"])
    await gw(p, sleeper=s, max_delay=30).complete(req())
    assert s.delays == [7.0, 30.0]


async def test_permanent_error_not_retried_and_no_fallback():
    p, f = FakeProvider([LLMPermanentError("401")]), FakeProvider(["ok"], name="fb")
    with pytest.raises(LLMPermanentError):
        await gw(p, [f]).complete(req())
    assert len(p.calls) == 1 and len(f.calls) == 0


async def test_fallback_after_primary_exhausted():
    p, f = FakeProvider([LLMTransientError("x")]), FakeProvider(["from-fb"], name="fb")
    r = await gw(p, [f]).complete(req())
    assert r.text == "from-fb" and len(p.calls) == 3 and r.provider == "fb"
    assert r.model == "m2"


async def test_all_targets_fail_raises_bounded():
    p, f = FakeProvider([LLMTransientError("x")]), FakeProvider([LLMTransientError("y")], name="fb")
    with pytest.raises(LLMTransientError, match="all 2"):
        await gw(p, [f]).complete(req())
    assert len(p.calls) == 3 and len(f.calls) == 3  # bounded: no endless loops


async def test_timeout_is_enforced_and_retried():
    p = FakeProvider(["late"], delay=0.5)
    g = gw(p, timeout=0.02, max_attempts=2)
    with pytest.raises(LLMTransientError, match="deadline exceeded"):
        await g.complete(req())
    assert len(p.calls) == 2
    assert all(r.error_type == "LLMTimeoutError" for r in g.tracker.records)


async def test_concurrency_is_bounded():
    p = FakeProvider(["ok"], delay=0.02)
    g = LLMGateway(Target(p, "m1"), max_concurrency=2, sleep=Sleeper())
    await asyncio.gather(*(g.complete(req()) for _ in range(8)))
    assert p.max_in_flight == 2


class Brief(BaseModel):
    title: str
    n: int


async def test_structured_parses_plain_and_fenced_json():
    g = gw(FakeProvider(['```json\n{"title": "a", "n": 2}\n```']))
    obj, _ = await g.complete_structured(req(), Brief)
    assert obj == Brief(title="a", n=2)
    sent = g._targets[0].provider.calls[0]
    assert "JSON Schema" in (sent.system or "") and "title" in (sent.system or "")


async def test_structured_reasks_once_on_invalid_output():
    p = FakeProvider(["not json", '{"title": "ok", "n": 1}'])
    obj, _ = await gw(p).complete_structured(req(), Brief)
    assert obj.title == "ok" and len(p.calls) == 2
    assert p.calls[1].messages[-1].role == "user" and "not valid" in p.calls[1].messages[-1].content


async def test_structured_fails_after_bounded_attempts():
    p = FakeProvider(['{"title": 1}'])
    with pytest.raises(LLMStructuredOutputError):
        await gw(p).complete_structured(req(), Brief)
    assert len(p.calls) == 2


async def test_request_validation():
    with pytest.raises(ValueError):
        LLMRequest(messages=[])
