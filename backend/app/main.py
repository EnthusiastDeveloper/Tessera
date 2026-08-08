"""Tessera task scheduling application."""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.middleware import AuthGuardMiddleware
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.settings import router as settings_router
from app.auth.service import apply_reset_admin_password_if_needed
from app.auth.setup_token import setup_token_store
from app.core.config import get_settings
from app.db.repositories import UserRepository
from app.db.session import session_scope
from app.settings.service import default_timezone_from_env, get_or_create_default

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan - see design doc §3.6 (setup token), §6.1 (cookie Secure logging)."""
    logger.info("Tessera starting up")

    settings = get_settings()
    secure = settings.resolve_session_cookie_secure()
    logger.info("Session cookie Secure=%s (SESSION_COOKIE_SECURE=%s)", secure, settings.session_cookie_secure)
    if not secure:
        logger.warning(
            "Session cookie is NOT marked Secure - the session cookie and login password "
            "cross the network in cleartext. Put a TLS-terminating reverse proxy (or "
            "WireGuard/Tailscale) in front of Tessera if it's reachable beyond localhost."
        )

    with session_scope() as db:
        apply_reset_admin_password_if_needed(db, reset_value=settings.reset_admin_password)
        if UserRepository(db).count() == 0:
            token = setup_token_store.issue()
            logger.warning("No account exists yet. Setup token (use it at POST /api/v1/auth/setup): %s", token)

        default_timezone = default_timezone_from_env(settings.tz)
        if settings.tz and default_timezone == "UTC" and settings.tz != "UTC":
            logger.warning("TZ=%s is not a valid IANA timezone name - falling back to UTC.", settings.tz)
        get_or_create_default(db, default_timezone=default_timezone)

    yield
    logger.info("Tessera shutting down")


app = FastAPI(
    title="Tessera",
    description="Self-hosted task scheduling that respects the real shape of your day.",
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
)

register_error_handlers(app)
app.add_middleware(AuthGuardMiddleware)
app.include_router(auth_router)
app.include_router(settings_router)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint for container orchestration. Public (§14.2) - minimal payload
    only, nothing an unauthenticated caller can fingerprint.
    """
    return {"status": "ok"}


# Placeholder: in Stage 9, serve the frontend build here
# frontend_path = os.path.join(os.path.dirname(__file__), "../../frontend/dist")
# if os.path.exists(frontend_path):
#     app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
