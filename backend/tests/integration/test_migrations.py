"""Migration round-trip tests. See implementation-plan Stage 2 "Tests required".

Drives Alembic as a subprocess against a real temp-file SQLite DB, rather than in-process,
so each test gets a genuinely fresh interpreter - `app.core.config.get_settings()` is
`lru_cache`d, and calling it in-process from a prior test would pin `DATABASE_PATH` to a
stale value.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
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
    "schedule_repairs",
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


def test_the_baseline_matches_the_models_exactly(tmp_path: Path) -> None:
    """`alembic check` finds nothing to autogenerate: the models and the migration have not
    drifted apart. The baseline is edited by hand alongside the models (see its docstring), so
    this is what keeps the two honest."""
    db_path = tmp_path / "drift.db"
    _run_alembic("upgrade", "head", database_path=db_path)
    _run_alembic("check", database_path=db_path)


def test_there_is_exactly_one_migration(tmp_path: Path) -> None:
    """Until the first release holding data worth keeping, the schema is one baseline that is
    edited in place (its docstring says when that stops). A second file appearing is that
    policy changing - make it a decision, not an accident."""
    versions = sorted(path.name for path in (BACKEND_DIR / "alembic" / "versions").glob("*.py"))
    assert versions == ["0001_initial_schema.py"]


def test_database_level_constraints_survive_in_the_baseline(tmp_path: Path) -> None:
    """The CHECK constraints come from `sa.Enum(create_constraint=True)`; autogenerate emits
    them again as separate constraints, which the baseline leaves out - so make sure each is
    still enforced, once."""
    db_path = tmp_path / "constraints.db"
    _run_alembic("upgrade", "head", database_path=db_path)
    ts = "2026-03-01 12:00:00.000000"
    insert = (
        "INSERT INTO task_templates (id, name, type, recurrence_pattern, recurrence_anchor, priority,"
        " estimated_duration_minutes, reminder_offsets_minutes, archived, start_date, created_at, updated_at, version)"
        " VALUES ('t', 'x', 'flexible', ?, 'calendar', 2, 30, '[]', 0, '2026-03-01', ?, ?, 1)"
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(insert, ("daily", ts, ts))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert.replace("'t'", "'u'"), ("custom", ts, ts))
        (sql,) = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'task_templates'").fetchone()
    assert sql.count("CONSTRAINT recurrence_pattern") == 1
