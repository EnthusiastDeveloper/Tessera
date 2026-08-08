"""Repository for `User` rows. See design doc §3.6."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.user import UserORM
from app.db.schemas import User


class UserRepository:
    """CRUD for `User`. `count()` backs the setup wizard's "zero users" gate (§3.6, Stage 3)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, user: User) -> User:
        orm = UserORM(
            id=user.id,
            username=user.username,
            password_hash=user.password_hash,
            two_factor_enabled=user.two_factor_enabled,
            created_at=user.created_at,
        )
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, user_id: str) -> User | None:
        orm = self._session.get(UserORM, user_id)
        return _to_domain(orm) if orm is not None else None

    def get_by_username(self, username: str) -> User | None:
        orm = self._session.scalars(select(UserORM).where(UserORM.username == username)).first()
        return _to_domain(orm) if orm is not None else None

    def count(self) -> int:
        return self._session.scalar(select(func.count()).select_from(UserORM)) or 0

    def update(self, user: User) -> User:
        orm = self._session.get(UserORM, user.id)
        if orm is None:
            raise LookupError(f"User {user.id} not found")
        orm.username = user.username
        orm.password_hash = user.password_hash
        orm.two_factor_enabled = user.two_factor_enabled
        self._session.flush()
        return _to_domain(orm)


def _to_domain(orm: UserORM) -> User:
    return User(
        id=orm.id,
        username=orm.username,
        password_hash=orm.password_hash,
        two_factor_enabled=orm.two_factor_enabled,
        created_at=orm.created_at,
    )
