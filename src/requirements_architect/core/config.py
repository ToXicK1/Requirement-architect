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
    checkpoint_path: str = "./data/checkpoints.db"  # LangGraph state (SQLite; see ADR-041)
    output_dir: str = "./data/output"  # generated documentation packages are written here

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

    # --- Access control ---
    allow_registration: bool = False  # otherwise create users with the CLI
    session_ttl_hours: int = Field(default=12, ge=1, le=24 * 30)

    # --- Audit (Stage 11): bounded so it can never regenerate endlessly ---
    audit_max_rounds: int = Field(default=2, ge=0, le=5)
    audit_max_stage_runs: int = Field(default=12, ge=0, le=60)
    audit_max_major: int = Field(default=0, ge=0)
    audit_llm_review: bool = True

    # --- Research (Stage 3). All optional; absence is reported as a limitation, never faked. ---
    research_enabled: bool = True
    brave_api_key: SecretStr = SecretStr("")
    github_token: SecretStr = SecretStr("")
    research_allow_http: bool = False
    research_max_fetches: int = Field(default=10, ge=0, le=50)
    research_fetch_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    research_fetch_max_bytes: int = Field(default=2_000_000, gt=0, le=20_000_000)

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
