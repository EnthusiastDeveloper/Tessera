"""Repository for the `RESET_ADMIN_PASSWORD` marker singleton. See design doc §3.6."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.admin_password_reset_marker import AdminPasswordResetMarkerORM
from app.db.schemas import AdminPasswordResetMarker


class AdminPasswordResetMarkerRepository:
    """Singleton access, like `UserSettingsRepository` - at most one marker row ever exists."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self) -> AdminPasswordResetMarker | None:
        orm = self._session.scalars(select(AdminPasswordResetMarkerORM)).first()
        return _to_domain(orm) if orm is not None else None

    def upsert(self, marker: AdminPasswordResetMarker) -> AdminPasswordResetMarker:
        """Create the marker row if none exists yet, else overwrite it in place.

        `marker` must already carry a generated `id`, matching the other repositories'
        `create()` convention - it is only used the first time; a later upsert keeps the
        existing row's id.
        """
        existing = self._session.scalars(select(AdminPasswordResetMarkerORM)).first()
        if existing is None:
            orm = AdminPasswordResetMarkerORM(
                id=marker.id,
                consumed_value_hash=marker.consumed_value_hash,
                consumed_at=marker.consumed_at,
            )
            self._session.add(orm)
        else:
            orm = existing
            orm.consumed_value_hash = marker.consumed_value_hash
            orm.consumed_at = marker.consumed_at
        self._session.flush()
        return _to_domain(orm)


def _to_domain(orm: AdminPasswordResetMarkerORM) -> AdminPasswordResetMarker:
    return AdminPasswordResetMarker(
        id=orm.id,
        consumed_value_hash=orm.consumed_value_hash,
        consumed_at=orm.consumed_at,
    )
