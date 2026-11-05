"""Application settings with fail-fast validation at startup."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

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

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.app_env is AppEnv.PRODUCTION:
            if len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not permitted in production; use PostgreSQL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
