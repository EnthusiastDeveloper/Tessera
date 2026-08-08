"""Tests for the DB engine/session wiring itself - `sqlite_url`, `get_session_factory`, `get_db`.

Distinct from the repository tests, which all bypass this module's `lru_cache`d globals via
`build_engine("sqlite:///:memory:")` directly (see `tests/integration/conftest.py`).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, get_session_factory, sqlite_url


@pytest.fixture(autouse=True)
def _fresh_lru_caches() -> Iterator[None]:
    """`get_settings`/`get_session_factory` are process-wide caches - reset around each test."""
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    yield
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def test_sqlite_url_creates_the_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "tessera.db"
    url = sqlite_url(str(db_path))
    assert url == f"sqlite:///{db_path}"
    assert db_path.parent.is_dir()


def test_get_session_factory_binds_to_configured_database_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "tessera.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    session = get_session_factory()()
    try:
        assert str(db_path) in str(session.get_bind().url)
    finally:
        session.close()


def test_get_db_yields_a_usable_session_and_closes_it_afterward(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "tessera.db"))

    generator = get_db()
    session = next(generator)
    assert isinstance(session, Session)
    assert session.execute(text("SELECT 1")).scalar() == 1

    with pytest.raises(StopIteration):
        next(generator)  # exhausts the generator, running the `finally: session.close()`
