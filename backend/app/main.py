"""Tessera task scheduling application."""

import logging
import os
from collections.abc import AsyncGenerator, MutableMapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, NamedTuple

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import register_error_handlers
from app.api.middleware import AuthGuardMiddleware
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.calendar_connections import router as calendar_connections_router
from app.api.v1.routes.external_events import router as external_events_router
from app.api.v1.routes.notifications import router as notifications_router
from app.api.v1.routes.settings import router as settings_router
from app.api.v1.routes.task_instances import router as task_instances_router
from app.api.v1.routes.task_templates import router as task_templates_router
from app.auth.service import apply_reset_admin_password_if_needed
from app.auth.setup_token import setup_token_store
from app.core.config import get_settings
from app.db.repositories import UserRepository
from app.db.session import get_jobs_engine, session_scope
from app.jobs.interface import DEADLINE_ELAPSED_SWEEP_INTERVAL_MINUTES, DEADLINE_ELAPSED_SWEEP_JOB_KEY, set_job_scheduler
from app.jobs.reconciliation import reconcile_on_startup
from app.jobs.scheduler import APSchedulerJobScheduler
from app.jobs.transactional import TransactionalJobScheduler
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

    # Stage 6: the real job scheduler, persisted in its own SQLite file - deliberately not
    # the app's own (architecture-plan §4's persistence requirement; see
    # app.db.session.jobs_database_path for why a shared file doesn't work here). Installed
    # as the process-wide singleton before reconciliation runs and before the app starts
    # serving traffic, so no mutation can race ahead of it.
    job_scheduler = APSchedulerJobScheduler(get_jobs_engine())
    set_job_scheduler(job_scheduler)
    job_scheduler.start()

    with session_scope() as db:
        reconcile_on_startup(db, TransactionalJobScheduler(job_scheduler, db))
    job_scheduler.schedule_interval(job_key=DEADLINE_ELAPSED_SWEEP_JOB_KEY, minutes=DEADLINE_ELAPSED_SWEEP_INTERVAL_MINUTES)

    yield
    logger.info("Tessera shutting down")
    job_scheduler.shutdown(wait=False)


class _DocsUrls(NamedTuple):
    openapi_url: str | None
    docs_url: str | None
    redoc_url: str | None
    swagger_ui_oauth2_redirect_url: str | None


def _docs_urls(*, enable_api_docs: bool) -> _DocsUrls:
    """architecture-plan §6 "API docs in production" (Rev 3): disabled by default, opt-in
    via `ENABLE_API_DOCS`. Split into its own function so the on/off decision is directly
    unit-testable without constructing the real app.
    """
    if not enable_api_docs:
        return _DocsUrls(openapi_url=None, docs_url=None, redoc_url=None, swagger_ui_oauth2_redirect_url=None)
    return _DocsUrls(
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        # Default is "/docs/oauth2-redirect", outside the /api/ prefix used above - which
        # Stage 10's frontend/SPA bypass (see AuthGuardMiddleware._is_frontend_request)
        # would otherwise treat as a public static path rather than a guarded API route.
        swagger_ui_oauth2_redirect_url="/api/v1/docs/oauth2-redirect",
    )


_docs = _docs_urls(enable_api_docs=get_settings().enable_api_docs)

app = FastAPI(
    title="Tessera",
    description="Self-hosted task scheduling that respects the real shape of your day.",
    version="0.1.0",
    openapi_url=_docs.openapi_url,
    docs_url=_docs.docs_url,
    redoc_url=_docs.redoc_url,
    swagger_ui_oauth2_redirect_url=_docs.swagger_ui_oauth2_redirect_url,
    lifespan=lifespan,
)

register_error_handlers(app)
app.add_middleware(AuthGuardMiddleware)
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(task_templates_router)
app.include_router(task_instances_router)
app.include_router(notifications_router)
app.include_router(calendar_connections_router)
app.include_router(external_events_router)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint for container orchestration. Public (§14.2) - minimal payload
    only, nothing an unauthenticated caller can fingerprint.
    """
    return {"status": "ok"}


class SPAStaticFiles(StaticFiles):
    """Serves the built frontend; falls back to `index.html` for unknown paths so
    React Router's client-side routes (e.g. a deep-linked `/timeline`) survive a hard
    reload. Mounted last (architecture-plan §7 - same-origin), so any real `/api/...`
    route above already claimed the request before this ever sees it; the `api/` guard
    below is just belt-and-suspenders against a stale/removed endpoint falling through
    to a misleading 200 instead of a real 404.
    """

    async def get_response(self, path: str, scope: MutableMapping[str, Any]) -> Any:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


# Populated by the Dockerfile's frontend-builder stage into ./static (architecture-plan
# §7); absent in local backend-only dev, where the frontend runs via its own Vite dev
# server instead - so the mount is conditional, not assumed.
_frontend_dir = Path(__file__).resolve().parent.parent / "static"
if _frontend_dir.is_dir():
    app.mount("/", SPAStaticFiles(directory=_frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
