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
from app.db.session import build_engine, get_db, get_engine, get_jobs_engine, get_session_factory, sqlite_url


@pytest.fixture(autouse=True)
def _fresh_lru_caches() -> Iterator[None]:
    """`get_settings`/`get_engine`/`get_jobs_engine`/`get_session_factory` are process-wide caches - reset around each test."""
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_jobs_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_jobs_engine.cache_clear()
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


def test_every_connection_gets_the_documented_sqlite_pragmas(tmp_path: Path) -> None:
    """architecture-plan §5.3 (IRR-2 M12): foreign keys on, WAL journal, 5 s busy timeout.
    A file database, since `:memory:` cannot use WAL."""
    engine = build_engine(sqlite_url(str(tmp_path / "pragmas.db")))
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000
