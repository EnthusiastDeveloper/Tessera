"""Application configuration. See architecture-plan §7.1 for the full env var reference."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

SessionCookieSecureSetting = Literal["auto", "true", "false"]


class Settings(BaseSettings):
    """Environment-sourced configuration. See `.env.example` for the canonical variable list."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_path: str = "./data/tessera.db"

    # --- Auth (Stage 3) ---
    secret_key: str  # required: session cookie signing + Fernet encryption of OAuth tokens (Stage 7)
    session_cookie_secure: SessionCookieSecureSetting = "auto"
    app_base_url: str | None = None  # required only if SESSION_COOKIE_SECURE=auto, or calendar sync (Stage 7)
    reset_admin_password: str | None = None  # one-time recovery trigger, design doc §3.6
    # /docs, /redoc, /openapi.json would otherwise expose the whole API surface
    # uncredentialed - architecture-plan §6 "API docs in production" (Rev 3), closed in
    # Stage 11. False by default (secure by default); the auth guard already blocks
    # unauthenticated access to them regardless (Stage 9a's SETUP_ALLOWED_ROUTES), so this
    # is defense-in-depth on top of that, not the only thing standing between them and the
    # internet.
    enable_api_docs: bool = False

    # --- Settings (Stage 4) ---
    tz: str | None = None  # default timezone for the first-run UserSettings row, design doc §14.1

    # --- Calendar sync (Stage 7) ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    outlook_client_id: str | None = None
    outlook_client_secret: str | None = None

    def resolve_session_cookie_secure(self) -> bool:
        """Whether the session cookie should carry `Secure`. See architecture-plan §6.1.

        `auto` derives it from `APP_BASE_URL`'s scheme so plain-HTTP LAN deployments -
        an explicitly supported target, not a degraded mode - don't silently drop the
        cookie (browsers refuse `Secure` cookies over plain HTTP except on localhost).
        """
        if self.session_cookie_secure == "true":
            return True
        if self.session_cookie_secure == "false":
            return False
        if self.app_base_url is None:
            return False
        return self.app_base_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()
