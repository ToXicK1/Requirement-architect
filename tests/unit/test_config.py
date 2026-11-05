import pytest
from pydantic import ValidationError

from requirements_architect.core.config import AppEnv, Settings


def _mk(**kw):
    return Settings(_env_file=None, **kw)


def test_defaults_are_development():
    assert _mk().app_env is AppEnv.DEVELOPMENT


def test_production_requires_strong_secret():
    with pytest.raises(ValidationError):
        _mk(app_env="production", database_url="postgresql+asyncpg://u:p@h/db", secret_key="short")


def test_production_rejects_sqlite():
    with pytest.raises(ValidationError):
        _mk(app_env="production", secret_key="x" * 40)


def test_production_valid():
    s = _mk(
        app_env="production",
        secret_key="x" * 40,
        database_url="postgresql+asyncpg://u:p@h/db",
        llm_provider="anthropic",
        llm_api_key="k",
        llm_model="m",
    )
    assert s.app_env is AppEnv.PRODUCTION and s.llm_configured


def test_production_requires_llm():
    with pytest.raises(ValidationError):
        _mk(app_env="production", secret_key="x" * 40, database_url="postgresql+asyncpg://u:p@h/db")


def test_llm_provider_without_key_rejected():
    with pytest.raises(ValidationError):
        _mk(llm_provider="anthropic", llm_model="m")


def test_api_key_not_in_repr():
    assert "supersecret" not in repr(_mk(llm_api_key="supersecret"))


def test_invalid_log_level_rejected():
    with pytest.raises(ValidationError):
        _mk(log_level="LOUD")
