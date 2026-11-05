import httpx
import pytest

from requirements_architect.core.config import Settings
from requirements_architect.llm.factory import build_gateway, parse_price_table
from requirements_architect.llm.types import LLMConfigError


def mk(**kw):
    return Settings(_env_file=None, **kw)


async def test_builds_primary_and_fallback():
    s = mk(
        llm_provider="anthropic",
        llm_api_key="k",
        llm_model="a",
        llm_fallback_provider="openai_compat",
        llm_fallback_api_key="k2",
        llm_fallback_model="b",
        llm_price_table_json='{"a": {"input_per_mtok": "1", "output_per_mtok": "2"}}',
    )
    async with httpx.AsyncClient() as c:
        g = build_gateway(s, c)
    assert [t.provider.name for t in g._targets] == ["anthropic", "openai_compat"]
    assert [t.model for t in g._targets] == ["a", "b"]


async def test_unconfigured_raises():
    async with httpx.AsyncClient() as c:
        with pytest.raises(LLMConfigError):
            build_gateway(mk(), c)


@pytest.mark.parametrize("raw", ["not json", '{"m": {"input_per_mtok": "x"}}', "[1]"])
def test_invalid_price_table(raw):
    with pytest.raises(LLMConfigError):
        parse_price_table(raw)
