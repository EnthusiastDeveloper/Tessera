"""Calendar-connection endpoints: OAuth connect/disconnect, list. See design doc §3.5,
§7; architecture-plan §6.

The provider callback is deliberately a plain `GET` (not routed through a POST-only
mutation) - architecture-plan §6.1's "no state-changing endpoint may be exposed over GET"
rule exists to prevent a forged cross-site `GET` from performing a mutation under `Lax`'s
cover, but the OAuth callback carries its own per-request, session-bound, signed, and
short-lived `state` parameter (architecture-plan §6, mandatory since Rev 3) - exactly the
per-request unguessable-token property that rule is protecting against the absence of.
It is also not in the auth-guard's public allowlist (`app.api.middleware`), so it already
requires the valid session `SameSite=Lax` was chosen to still deliver on this exact
cross-site top-level navigation (design doc §14.2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_request_job_scheduler
from app.api.errors import AppError
from app.calendar_sync import service
from app.core.config import get_settings
from app.db.base import utcnow
from app.db.schemas import CalendarProvider, ExternalCalendarConnection
from app.db.session import get_db
from app.jobs.interface import JobScheduler

router = APIRouter(prefix="/api/v1/calendar-connections", tags=["calendar-connections"])


def _callback_redirect_uri(provider: CalendarProvider, *, app_base_url: str) -> str:
    return f"{app_base_url.rstrip('/')}/api/v1/calendar-connections/{provider}/callback"


def _require_app_base_url() -> str:
    app_base_url = get_settings().app_base_url
    if not app_base_url:
        raise AppError.for_code("app_base_url_not_configured", "APP_BASE_URL must be set to use calendar sync.")
    return app_base_url


@router.get("")
def list_connections_endpoint(db: Session = Depends(get_db)) -> list[ExternalCalendarConnection]:
    return list(service.list_connections(db))


@router.get("/{provider}/connect")
def connect_endpoint(
    provider: CalendarProvider,
    request: Request,
    refresh_interval_minutes: int = service.DEFAULT_REFRESH_INTERVAL_MINUTES,
) -> dict[str, str]:
    app_base_url = _require_app_base_url()
    try:
        result = service.build_authorize_url(
            provider=provider,
            session_id=request.state.session_id,
            redirect_uri=_callback_redirect_uri(provider, app_base_url=app_base_url),
            refresh_interval_minutes=refresh_interval_minutes,
            app_settings=get_settings(),
        )
    except service.CalendarSyncError as exc:
        raise AppError.for_code(exc.code, str(exc)) from exc
    return {"authorize_url": result.authorize_url}


@router.get("/{provider}/callback")
def callback_endpoint(
    provider: CalendarProvider,
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
    jobs: JobScheduler = Depends(get_request_job_scheduler),
) -> RedirectResponse:
    app_base_url = _require_app_base_url()
    try:
        service.complete_oauth_callback(
            db,
            jobs,
            provider=provider,
            code=code,
            state=state,
            session_id=request.state.session_id,
            redirect_uri=_callback_redirect_uri(provider, app_base_url=app_base_url),
            app_settings=get_settings(),
            now=utcnow(),
        )
    except service.CalendarSyncError as exc:
        raise AppError.for_code(exc.code, str(exc)) from exc
    # No frontend route exists yet (Stage 9) - land back on the app root with a query
    # flag it can pick up once it does, rather than returning a bare JSON body to what is
    # a real browser top-level navigation.
    return RedirectResponse(url=f"{app_base_url.rstrip('/')}/?calendar_connected={provider}")


@router.delete("/{connection_id}", status_code=204)
def disconnect_endpoint(
    connection_id: str, db: Session = Depends(get_db), jobs: JobScheduler = Depends(get_request_job_scheduler)
) -> None:
    try:
        service.disconnect(db, jobs, connection_id)
    except service.CalendarSyncError as exc:
        raise AppError.for_code(exc.code, str(exc)) from exc
