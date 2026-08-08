"""Repository CRUD tests for `User`. See design doc §3.6."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.repositories import UserRepository
from tests.fixtures.db_entities import make_user


def test_create_and_get_round_trip(db_session: Session) -> None:
    repo = UserRepository(db_session)
    user = make_user(username="admin")
    created = repo.create(user)
    db_session.commit()
    db_session.expire_all()

    assert repo.get(user.id) == created


def test_get_by_username(db_session: Session) -> None:
    repo = UserRepository(db_session)
    created = repo.create(make_user(username="admin"))
    db_session.commit()

    assert repo.get_by_username("admin") == created
    assert repo.get_by_username("nobody") is None


def test_count_reflects_row_count(db_session: Session) -> None:
    repo = UserRepository(db_session)
    assert repo.count() == 0

    repo.create(make_user())
    db_session.commit()

    assert repo.count() == 1


def test_update_persists_password_hash_change(db_session: Session) -> None:
    repo = UserRepository(db_session)
    created = repo.create(make_user())
    db_session.commit()

    updated = repo.update(created.model_copy(update={"password_hash": "argon2id$new-hash"}))
    db_session.commit()

    assert updated.password_hash == "argon2id$new-hash"
