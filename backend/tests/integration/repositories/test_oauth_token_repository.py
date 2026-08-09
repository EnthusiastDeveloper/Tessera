"""Repository CRUD tests for `OAuthToken`. See design doc §3.5, architecture-plan §6."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.repositories import OAuthTokenRepository
from tests.fixtures.db_entities import make_oauth_token


def test_create_and_get_round_trip(db_session: Session) -> None:
    repo = OAuthTokenRepository(db_session)
    token = make_oauth_token()
    created = repo.create(token)
    db_session.commit()
    db_session.expire_all()

    fetched = repo.get(token.id)
    assert fetched == created


def test_update_persists_changes(db_session: Session) -> None:
    repo = OAuthTokenRepository(db_session)
    created = repo.create(make_oauth_token(encrypted_refresh_token="old"))
    db_session.commit()

    updated = repo.update(created.model_copy(update={"encrypted_refresh_token": "new"}))
    db_session.commit()

    assert updated.encrypted_refresh_token == "new"


def test_delete_is_idempotent(db_session: Session) -> None:
    repo = OAuthTokenRepository(db_session)
    created = repo.create(make_oauth_token())
    db_session.commit()

    repo.delete(created.id)
    repo.delete(created.id)  # second call must not raise
    db_session.commit()

    assert repo.get(created.id) is None
