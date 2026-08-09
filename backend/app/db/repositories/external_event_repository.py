"""Repository for `ExternalEvent` rows. See design doc §3.11, §3.12 (retention), §6.4 (sync diff)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.external_event import ExternalEventORM
from app.db.schemas import ExternalEvent


class ExternalEventRepository:
    """CRUD, plus the upsert §3.11 says the `(connection_id, provider_event_id)` uniqueness enables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_provider_event_id(self, connection_id: str, provider_event_id: str) -> ExternalEvent | None:
        stmt = select(ExternalEventORM).where(
            ExternalEventORM.connection_id == connection_id,
            ExternalEventORM.provider_event_id == provider_event_id,
        )
        orm = self._session.scalars(stmt).first()
        return _to_domain(orm) if orm is not None else None

    def upsert(self, event: ExternalEvent) -> ExternalEvent:
        """Insert, or update in place if `(connection_id, provider_event_id)` already exists (§3.11, §6.4)."""
        return self.upsert_and_diff(event)[0]

    def upsert_and_diff(self, event: ExternalEvent) -> tuple[ExternalEvent, bool]:
        """Same as `upsert`, but also reports whether this is a new row, or an existing one
        whose `start`/`end`/`is_all_day`/`is_transparent` changed, or one that was
        previously soft-deleted and has reappeared - §6.4 step 3's "new/moved" collision
        trigger, which needs exactly this comparison. Saves the caller (`app.calendar_sync.
        service.sync_connection`) a separate `get_by_provider_event_id` lookup per event,
        since `upsert` already has to fetch `existing` to decide insert-vs-update anyway.
        """
        existing = self._session.scalars(
            select(ExternalEventORM).where(
                ExternalEventORM.connection_id == event.connection_id,
                ExternalEventORM.provider_event_id == event.provider_event_id,
            )
        ).first()
        changed = (
            existing is None
            or existing.start != event.start
            or existing.end != event.end
            or existing.is_all_day != event.is_all_day
            or existing.is_transparent != event.is_transparent
            or existing.deleted_at is not None
        )
        if existing is None:
            orm = ExternalEventORM(**_to_orm_kwargs(event))
            self._session.add(orm)
        else:
            orm = existing
            for key, value in _to_orm_kwargs(event).items():
                if key != "id":
                    setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm), changed

    def list_active_for_connection(self, connection_id: str) -> tuple[ExternalEvent, ...]:
        """Non-soft-deleted cached events - the obstacle set the engine reads (§6.2, §3.11)."""
        stmt = select(ExternalEventORM).where(
            ExternalEventORM.connection_id == connection_id,
            ExternalEventORM.deleted_at.is_(None),
        )
        return tuple(_to_domain(orm) for orm in self._session.scalars(stmt))

    def purge_ended_before(self, connection_id: str, cutoff: datetime) -> int:
        """§3.12's retention sweep: hard-delete rows (soft-deleted or not) whose `end` is
        more than 30 days past, run on the same poll pass as the diff (§6.4 step 1).
        Returns the number of rows purged.
        """
        ids = list(
            self._session.scalars(
                select(ExternalEventORM.id).where(
                    ExternalEventORM.connection_id == connection_id,
                    ExternalEventORM.end < cutoff,
                )
            )
        )
        if ids:
            self._session.execute(delete(ExternalEventORM).where(ExternalEventORM.id.in_(ids)))
            self._session.flush()
        return len(ids)


def _to_orm_kwargs(event: ExternalEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "connection_id": event.connection_id,
        "provider_event_id": event.provider_event_id,
        "start": event.start,
        "end": event.end,
        "title": event.title,
        "is_all_day": event.is_all_day,
        "is_transparent": event.is_transparent,
        "fetched_at": event.fetched_at,
        "deleted_at": event.deleted_at,
    }


def _to_domain(orm: ExternalEventORM) -> ExternalEvent:
    return ExternalEvent(
        id=orm.id,
        connection_id=orm.connection_id,
        provider_event_id=orm.provider_event_id,
        start=orm.start,
        end=orm.end,
        title=orm.title,
        is_all_day=orm.is_all_day,
        is_transparent=orm.is_transparent,
        fetched_at=orm.fetched_at,
        deleted_at=orm.deleted_at,
    )
