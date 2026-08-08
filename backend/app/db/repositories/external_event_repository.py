"""Repository for `ExternalEvent` rows. See design doc §3.11, §3.12 (retention), §6.4 (sync diff)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
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
        existing = self._session.scalars(
            select(ExternalEventORM).where(
                ExternalEventORM.connection_id == event.connection_id,
                ExternalEventORM.provider_event_id == event.provider_event_id,
            )
        ).first()
        if existing is None:
            orm = ExternalEventORM(**_to_orm_kwargs(event))
            self._session.add(orm)
        else:
            orm = existing
            for key, value in _to_orm_kwargs(event).items():
                if key != "id":
                    setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm)

    def list_active_for_connection(self, connection_id: str) -> tuple[ExternalEvent, ...]:
        """Non-soft-deleted cached events - the obstacle set the engine reads (§6.2, §3.11)."""
        stmt = select(ExternalEventORM).where(
            ExternalEventORM.connection_id == connection_id,
            ExternalEventORM.deleted_at.is_(None),
        )
        return tuple(_to_domain(orm) for orm in self._session.scalars(stmt))


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
