"""Application settings with fail-fast validation at startup."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    database_url: str = "sqlite+aiosqlite:///./requirements_architect.db"
    secret_key: SecretStr = SecretStr("")

    # --- LLM gateway (provider-independent; no default vendor model is assumed) ---
    llm_provider: Literal["anthropic", "openai_compat"] | None = None
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_base_url: str | None = None
    llm_fallback_provider: Literal["anthropic", "openai_compat"] | None = None
    llm_fallback_api_key: SecretStr = SecretStr("")
    llm_fallback_model: str = ""
    llm_fallback_base_url: str | None = None
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_max_attempts: int = Field(default=3, ge=1, le=10)
    llm_max_concurrency: int = Field(default=4, ge=1, le=64)
    # JSON object: {"model-name": {"input_per_mtok": "3.0", "output_per_mtok": "15.0"}}
    llm_price_table_json: str = "{}"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_provider and self.llm_api_key.get_secret_value() and self.llm_model)

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.llm_provider and not (self.llm_model and self.llm_api_key.get_secret_value()):
            raise ValueError("LLM_PROVIDER set but LLM_MODEL or LLM_API_KEY is missing")
        if self.llm_fallback_provider and not (
            self.llm_fallback_model and self.llm_fallback_api_key.get_secret_value()
        ):
            raise ValueError("LLM_FALLBACK_PROVIDER set but its model or API key is missing")
        if self.app_env is AppEnv.PRODUCTION:
            if not self.llm_configured:
                raise ValueError("LLM provider, model and API key are required in production")
            if len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not permitted in production; use PostgreSQL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
