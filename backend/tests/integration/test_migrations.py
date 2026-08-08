"""Migration round-trip tests. See implementation-plan Stage 2 "Tests required".

Drives Alembic as a subprocess against a real temp-file SQLite DB, rather than in-process,
so each test gets a genuinely fresh interpreter - `app.core.config.get_settings()` is
`lru_cache`d, and calling it in-process from a prior test would pin `DATABASE_PATH` to a
stale value.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "users",
    "user_settings",
    "task_templates",
    "task_instances",
    "task_instance_dependencies",
    "notifications",
    "external_calendar_connections",
    "external_events",
}


def _run_alembic(*args: str, database_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_PATH": str(database_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def _table_names(database_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{database_path}")
    return set(inspect(engine).get_table_names())


def test_upgrade_head_creates_every_entity_table(tmp_path: Path) -> None:
    db_path = tmp_path / "upgrade.db"
    _run_alembic("upgrade", "head", database_path=db_path)
    assert EXPECTED_TABLES <= _table_names(db_path)


def test_downgrade_base_removes_every_entity_table(tmp_path: Path) -> None:
    db_path = tmp_path / "downgrade.db"
    _run_alembic("upgrade", "head", database_path=db_path)
    _run_alembic("downgrade", "base", database_path=db_path)
    assert _table_names(db_path).isdisjoint(EXPECTED_TABLES)


def test_upgrade_downgrade_upgrade_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "roundtrip.db"
    _run_alembic("upgrade", "head", database_path=db_path)
    _run_alembic("downgrade", "base", database_path=db_path)
    _run_alembic("upgrade", "head", database_path=db_path)
    assert EXPECTED_TABLES <= _table_names(db_path)
