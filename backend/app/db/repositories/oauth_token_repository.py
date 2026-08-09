"""Repository for `OAuthToken` rows. See design doc §3.5, architecture-plan §6."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.oauth_token import OAuthTokenORM
from app.db.schemas import OAuthToken


class OAuthTokenRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, token: OAuthToken) -> OAuthToken:
        orm = OAuthTokenORM(**_to_orm_kwargs(token))
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, token_id: str) -> OAuthToken | None:
        orm = self._session.get(OAuthTokenORM, token_id)
        return _to_domain(orm) if orm is not None else None

    def update(self, token: OAuthToken) -> OAuthToken:
        orm = self._session.get(OAuthTokenORM, token.id)
        if orm is None:
            raise LookupError(f"OAuthToken {token.id} not found")
        for key, value in _to_orm_kwargs(token).items():
            if key != "id":
                setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm)

    def delete(self, token_id: str) -> None:
        """Idempotent - a token already gone is not an error (mirrors `SessionRepository.delete`)."""
        orm = self._session.get(OAuthTokenORM, token_id)
        if orm is not None:
            self._session.delete(orm)
            self._session.flush()


def _to_orm_kwargs(token: OAuthToken) -> dict[str, object]:
    return {
        "id": token.id,
        "encrypted_access_token": token.encrypted_access_token,
        "encrypted_refresh_token": token.encrypted_refresh_token,
        "access_token_expires_at": token.access_token_expires_at,
        "created_at": token.created_at,
        "updated_at": token.updated_at,
    }


def _to_domain(orm: OAuthTokenORM) -> OAuthToken:
    return OAuthToken(
        id=orm.id,
        encrypted_access_token=orm.encrypted_access_token,
        encrypted_refresh_token=orm.encrypted_refresh_token,
        access_token_expires_at=orm.access_token_expires_at,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )
