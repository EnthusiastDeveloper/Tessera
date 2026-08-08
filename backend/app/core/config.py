"""Application configuration. See architecture-plan §7.1 for the full env var reference.

Only the settings the data access layer needs (Stage 2) are defined here. Auth/session,
OAuth and calendar-provider settings are added by the stages that consume them.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-sourced configuration. See `.env.example` for the canonical variable list."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_path: str = "./data/tessera.db"


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()
