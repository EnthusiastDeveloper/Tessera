"""Repository for `ExternalCalendarConnection` rows. See design doc §3.5."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.external_calendar_connection import ExternalCalendarConnectionORM
from app.db.schemas import CalendarProvider, ExternalCalendarConnection


class ExternalCalendarConnectionRepository:
    """CRUD for `ExternalCalendarConnection`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, connection: ExternalCalendarConnection) -> ExternalCalendarConnection:
        orm = ExternalCalendarConnectionORM(**_to_orm_kwargs(connection))
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, connection_id: str) -> ExternalCalendarConnection | None:
        orm = self._session.get(ExternalCalendarConnectionORM, connection_id)
        return _to_domain(orm) if orm is not None else None

    def list(self, *, enabled_only: bool = False) -> tuple[ExternalCalendarConnection, ...]:
        """§6.4's poll job iterates enabled connections; the Settings screen lists all of them."""
        stmt = select(ExternalCalendarConnectionORM)
        if enabled_only:
            stmt = stmt.where(ExternalCalendarConnectionORM.enabled.is_(True))
        return tuple(_to_domain(orm) for orm in self._session.scalars(stmt))

    def update(self, connection: ExternalCalendarConnection) -> ExternalCalendarConnection:
        orm = self._session.get(ExternalCalendarConnectionORM, connection.id)
        if orm is None:
            raise LookupError(f"ExternalCalendarConnection {connection.id} not found")
        for key, value in _to_orm_kwargs(connection).items():
            if key != "id":
                setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm)

    def delete(self, connection_id: str) -> None:
        orm = self._session.get(ExternalCalendarConnectionORM, connection_id)
        if orm is None:
            raise LookupError(f"ExternalCalendarConnection {connection_id} not found")
        self._session.delete(orm)
        self._session.flush()


def _to_orm_kwargs(connection: ExternalCalendarConnection) -> dict[str, Any]:
    return {
        "id": connection.id,
        "provider": connection.provider,
        "oauth_credentials_ref": connection.oauth_credentials_ref,
        "refresh_interval_minutes": connection.refresh_interval_minutes,
        "last_synced_at": connection.last_synced_at,
        "sync_mode": connection.sync_mode,
        "enabled": connection.enabled,
    }


def _to_domain(orm: ExternalCalendarConnectionORM) -> ExternalCalendarConnection:
    return ExternalCalendarConnection(
        id=orm.id,
        provider=cast(CalendarProvider, orm.provider),
        oauth_credentials_ref=orm.oauth_credentials_ref,
        refresh_interval_minutes=orm.refresh_interval_minutes,
        last_synced_at=orm.last_synced_at,
        sync_mode="read_only",
        enabled=orm.enabled,
    )
