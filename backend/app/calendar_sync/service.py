"""External calendar sync: OAuth connect/disconnect, poll, §6.4 collision handling. See
design doc §3.5, §3.11, §3.12, §6.4, §7; architecture-plan §6.

Framework-agnostic like every other service-layer module - no FastAPI imports here
(`app.api.v1.routes.calendar_connections` is the thin HTTP wrapper).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy.orm import Session

from app.calendar_sync import token_crypto
from app.calendar_sync.oauth_state import generate_state, verify_state
from app.calendar_sync.providers.base import CalendarProviderClient, ProviderError
from app.calendar_sync.providers.registry import ProviderNotConfiguredError, get_provider_client
from app.core.config import Settings
from app.db.base import generate_id
from app.db.repositories import (
    ExternalCalendarConnectionRepository,
    ExternalEventRepository,
    NotificationRepository,
    OAuthTokenRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
    UserSettingsRepository,
)
from app.db.schemas import (
    CalendarProvider,
    ExternalCalendarConnection,
    ExternalEvent,
    Notification,
    NotificationType,
    OAuthToken,
    StatusHistoryEntry,
)
from app.jobs.interface import JobScheduler, calendar_poll_job_key
from app.scheduling.adapter import find_overlapping_scheduled_instances
from app.scheduling.orchestration import SYNC_CONFLICT, place_or_defer, resolve_cleared_sync_conflicts

#: §7: "a rolling 90-day forward horizon" - the poll's fetch window.
SYNC_HORIZON_DAYS = 90
#: §3.12: "purges events whose `end` is more than 30 days past" on the same poll pass.
RETENTION_PAST_DAYS = 30
#: Not specified by either source doc for the OAuth-connect-time default - matches the
#: existing §6.7 sweep's cadence (`DEADLINE_ELAPSED_SWEEP_INTERVAL_MINUTES`) as a
#: reasonable POC default; always overridable per-connection via the connect flow.
DEFAULT_REFRESH_INTERVAL_MINUTES = 15


class CalendarSyncError(Exception):
    """`code` maps to the API error envelope (architecture-plan §3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AuthorizeResult:
    authorize_url: str
    state: str


def list_connections(db: Session) -> tuple[ExternalCalendarConnection, ...]:
    return ExternalCalendarConnectionRepository(db).list()


def build_authorize_url(
    *, provider: CalendarProvider, session_id: str, redirect_uri: str, refresh_interval_minutes: int, app_settings: Settings
) -> AuthorizeResult:
    """Step 1 of the connect flow - never touches the database. `state` is mandatory
    (architecture-plan §6) and stateless (`app.calendar_sync.oauth_state`), so nothing
    needs to be persisted between this call and the callback.
    """
    client = _require_provider_client(provider, app_settings=app_settings)
    state = generate_state(
        session_id=session_id,
        provider=provider,
        refresh_interval_minutes=refresh_interval_minutes,
        secret_key=app_settings.secret_key,
    )
    return AuthorizeResult(authorize_url=client.build_authorize_url(state=state, redirect_uri=redirect_uri), state=state)


def complete_oauth_callback(
    db: Session,
    jobs: JobScheduler,
    *,
    provider: CalendarProvider,
    code: str,
    state: str,
    session_id: str,
    redirect_uri: str,
    app_settings: Settings,
    now: datetime,
) -> ExternalCalendarConnection:
    """Step 2 - exchanges the code, encrypts and persists the tokens, creates the
    connection, and schedules its poll job, all in one call (architecture-plan §4.1's
    co-location rule: the DB write and the job side-effect happen together).
    """
    refresh_interval_minutes = verify_state(state, session_id=session_id, provider=provider, secret_key=app_settings.secret_key)
    if refresh_interval_minutes is None:
        raise CalendarSyncError("invalid_oauth_state", "OAuth state parameter is missing, expired, or does not match.")

    client = _require_provider_client(provider, app_settings=app_settings)
    try:
        tokens = client.exchange_code(code=code, redirect_uri=redirect_uri)
    except ProviderError as exc:
        raise CalendarSyncError("oauth_exchange_failed", str(exc)) from exc

    token_row = OAuthTokenRepository(db).create(
        OAuthToken(
            id=generate_id(),
            encrypted_access_token=token_crypto.encrypt(tokens.access_token, secret_key=app_settings.secret_key),
            encrypted_refresh_token=(
                token_crypto.encrypt(tokens.refresh_token, secret_key=app_settings.secret_key)
                if tokens.refresh_token is not None
                else None
            ),
            access_token_expires_at=tokens.expires_at,
            created_at=now,
            updated_at=now,
        )
    )
    connection = ExternalCalendarConnectionRepository(db).create(
        ExternalCalendarConnection(
            id=generate_id(),
            provider=provider,
            oauth_credentials_ref=token_row.id,
            refresh_interval_minutes=refresh_interval_minutes,
            sync_mode="read_only",
            enabled=True,
        )
    )
    jobs.schedule_interval(job_key=calendar_poll_job_key(connection.id), minutes=refresh_interval_minutes)
    return connection


def disconnect(db: Session, jobs: JobScheduler, connection_id: str) -> None:
    """Cancels the poll job, deletes the encrypted token row, then the connection itself -
    `ExternalEvent` rows cascade-delete via the FK's `ondelete="CASCADE"` (see
    `app.db.models.external_event`), so no separate cleanup is needed for the cache.
    """
    connection = ExternalCalendarConnectionRepository(db).get(connection_id)
    if connection is None:
        raise CalendarSyncError("not_found", f"ExternalCalendarConnection {connection_id} not found")

    jobs.cancel(job_key=calendar_poll_job_key(connection_id))
    OAuthTokenRepository(db).delete(connection.oauth_credentials_ref)
    ExternalCalendarConnectionRepository(db).delete(connection_id)


def sync_connection(
    db: Session, jobs: JobScheduler, *, connection: ExternalCalendarConnection, app_settings: Settings, now: datetime
) -> ExternalCalendarConnection:
    """One poll pass (§6.4): fetch, diff/upsert against the cache, retention purge,
    collision handling for new/moved events, and `sync_conflict` self-resolution.
    """
    token_repo = OAuthTokenRepository(db)
    token = token_repo.get(connection.oauth_credentials_ref)
    if token is None:
        raise CalendarSyncError("not_found", f"OAuth token for connection {connection.id} not found")

    client = _require_provider_client(connection.provider, app_settings=app_settings)
    access_token = token_crypto.decrypt(token.encrypted_access_token, secret_key=app_settings.secret_key)

    if token.access_token_expires_at <= now:
        if token.encrypted_refresh_token is None:
            raise CalendarSyncError(
                "token_refresh_failed", f"Access token for connection {connection.id} expired with no refresh token."
            )
        try:
            refreshed = client.refresh_access_token(
                refresh_token=token_crypto.decrypt(token.encrypted_refresh_token, secret_key=app_settings.secret_key)
            )
        except ProviderError as exc:
            raise CalendarSyncError("token_refresh_failed", str(exc)) from exc
        access_token = refreshed.access_token
        token = token_repo.update(
            token.model_copy(
                update={
                    "encrypted_access_token": token_crypto.encrypt(refreshed.access_token, secret_key=app_settings.secret_key),
                    "encrypted_refresh_token": (
                        token_crypto.encrypt(refreshed.refresh_token, secret_key=app_settings.secret_key)
                        if refreshed.refresh_token is not None
                        else token.encrypted_refresh_token
                    ),
                    "access_token_expires_at": refreshed.expires_at,
                    "updated_at": now,
                }
            )
        )

    horizon_start = now
    horizon_end = now + timedelta(days=SYNC_HORIZON_DAYS)
    try:
        provider_events = client.fetch_events(access_token=access_token, horizon_start=horizon_start, horizon_end=horizon_end)
    except ProviderError as exc:
        raise CalendarSyncError("calendar_fetch_failed", str(exc)) from exc

    event_repo = ExternalEventRepository(db)
    changed_events: list[ExternalEvent] = []
    seen_provider_ids: set[str] = set()

    for provider_event in provider_events:
        seen_provider_ids.add(provider_event.provider_event_id)
        existing = event_repo.get_by_provider_event_id(connection.id, provider_event.provider_event_id)
        moved = (
            existing is None
            or existing.start != provider_event.start
            or existing.end != provider_event.end
            or existing.deleted_at is not None
        )
        stored = event_repo.upsert(
            ExternalEvent(
                id=existing.id if existing is not None else generate_id(),
                connection_id=connection.id,
                provider_event_id=provider_event.provider_event_id,
                start=provider_event.start,
                end=provider_event.end,
                title=provider_event.title,
                is_all_day=provider_event.is_all_day,
                is_transparent=provider_event.is_transparent,
                fetched_at=now,
                deleted_at=None,
            )
        )
        if moved:
            changed_events.append(stored)

    # §6.4 step 1: soft-delete rows the provider no longer returns.
    for cached in event_repo.list_active_for_connection(connection.id):
        if cached.provider_event_id not in seen_provider_ids:
            event_repo.upsert(cached.model_copy(update={"deleted_at": now}))

    event_repo.purge_ended_before(connection.id, now - timedelta(days=RETENTION_PAST_DAYS))

    # §6.4 step 3: only new/moved events can introduce a *new* collision.
    for event in changed_events:
        if event.is_transparent or event.is_all_day:
            continue  # §7 filter - never an obstacle, never a collision source
        _handle_collision(db, jobs, event=event, app_settings=app_settings, now=now)

    resolve_cleared_sync_conflicts(db, now=now)

    return ExternalCalendarConnectionRepository(db).update(connection.model_copy(update={"last_synced_at": now}))


def _handle_collision(db: Session, jobs: JobScheduler, *, event: ExternalEvent, app_settings: Settings, now: datetime) -> None:
    for instance in find_overlapping_scheduled_instances(db, start=event.start, end=event.end):
        if instance.type == "fixed":
            if not _has_active_sync_conflict(db, instance.id):
                NotificationRepository(db).create(
                    Notification(
                        id=generate_id(),
                        type=cast(NotificationType, SYNC_CONFLICT),
                        related_instance_id=instance.id,
                        message=f'"{instance.name}" now collides with the external event "{event.title}".',
                        created_at=now,
                    )
                )
        else:
            template = TaskTemplateRepository(db).get(instance.template_id)
            settings = UserSettingsRepository(db).get()
            if template is None or settings is None:
                continue
            reverted = TaskInstanceRepository(db).update(
                instance.model_copy(
                    update={
                        "status": "pending",
                        "scheduled_time": None,
                        "status_history": (*instance.status_history, StatusHistoryEntry(status="pending", at=now)),
                    }
                )
            )
            place_or_defer(db, jobs, instance=reverted, template=template, settings=settings, now=now)


def _has_active_sync_conflict(db: Session, instance_id: str) -> bool:
    return any(
        n.type == SYNC_CONFLICT and n.resolved_at is None and n.dismissed_at is None
        for n in NotificationRepository(db).list_for_instance(instance_id)
    )


def _require_provider_client(provider: CalendarProvider, *, app_settings: Settings) -> CalendarProviderClient:
    try:
        return get_provider_client(provider, settings=app_settings)
    except ProviderNotConfiguredError as exc:
        raise CalendarSyncError("provider_not_configured", str(exc)) from exc


__all__ = [
    "DEFAULT_REFRESH_INTERVAL_MINUTES",
    "RETENTION_PAST_DAYS",
    "SYNC_HORIZON_DAYS",
    "AuthorizeResult",
    "CalendarSyncError",
    "build_authorize_url",
    "complete_oauth_callback",
    "disconnect",
    "list_connections",
    "sync_connection",
]
