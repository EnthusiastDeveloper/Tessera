"""Fixtures for full-stack (HTTP-level) auth integration tests.

These are the only tests in the suite that exercise `app.main`'s real `lifespan` -
setup-token issuance and the `RESET_ADMIN_PASSWORD` check both only run there.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.throttle import login_throttle
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import build_engine, get_session_factory, sqlite_url
from app.main import app


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A `TestClient` wired to an isolated, freshly-schema'd SQLite DB, with the real
    app lifespan actually running (entering the `with` block triggers it).
    """
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "tessera.db"))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-production-use")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    login_throttle.clear_all()  # module-global state; nothing else resets it between tests

    engine = build_engine(sqlite_url(str(tmp_path / "tessera.db")))
    Base.metadata.create_all(engine)
    engine.dispose()

    with TestClient(app) as client:
        yield client

    get_settings.cache_clear()
    get_session_factory.cache_clear()
