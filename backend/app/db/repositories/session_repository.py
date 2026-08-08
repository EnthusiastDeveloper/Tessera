"""Repository for session rows. See architecture-plan §6, §6.2 (lifetime/rotation/revocation)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.session import SessionORM
from app.db.schemas import UserSession


class SessionRepository:
    """CRUD for sessions, plus the specific operations §6.2 requires: revoke-all-for-user
    (on password change/reset) and delete-expired (swept lazily at login, not a background job).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, user_session: UserSession) -> UserSession:
        orm = SessionORM(
            id=user_session.id,
            user_id=user_session.user_id,
            created_at=user_session.created_at,
            expires_at=user_session.expires_at,
        )
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, session_id: str) -> UserSession | None:
        orm = self._session.get(SessionORM, session_id)
        return _to_domain(orm) if orm is not None else None

    def delete(self, session_id: str) -> None:
        """Idempotent - deleting an already-absent session is not an error (logout, §14.2)."""
        orm = self._session.get(SessionORM, session_id)
        if orm is not None:
            self._session.delete(orm)
            self._session.flush()

    def delete_all_for_user(self, user_id: str) -> None:
        """Revoke every session for `user_id` - mandatory on password change/reset (§6.2)."""
        self._session.execute(delete(SessionORM).where(SessionORM.user_id == user_id))
        self._session.flush()

    def delete_expired(self, now: datetime) -> int:
        """Sweep sessions whose `expires_at` has passed. Returns the number removed."""
        expired_ids = list(self._session.scalars(select(SessionORM.id).where(SessionORM.expires_at <= now)))
        if expired_ids:
            self._session.execute(delete(SessionORM).where(SessionORM.id.in_(expired_ids)))
            self._session.flush()
        return len(expired_ids)


def _to_domain(orm: SessionORM) -> UserSession:
    return UserSession(
        id=orm.id,
        user_id=orm.user_id,
        created_at=orm.created_at,
        expires_at=orm.expires_at,
    )
