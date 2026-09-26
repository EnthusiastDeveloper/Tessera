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


def test_nominal_date_backfill_reproduces_the_old_derivation(tmp_path: Path) -> None:
    """b7d2c41e9a10 stores each instance's nominal date. Existing rows get exactly what the
    code used to derive, so no series moves: flexible `deadline - deadline_offset_minutes`,
    fixed `scheduled_time`.
    """
    db_path = tmp_path / "backfill.db"
    _run_alembic("upgrade", "e03f2aeaad85", database_path=db_path)

    ts = "2026-03-01 12:00:00.000000"
    with sqlite3.connect(db_path) as conn:
        for template_id, type_, offset in (("t-flex", "flexible", 1440), ("t-fixed", "fixed", None)):
            conn.execute(
                "INSERT INTO task_templates (id, name, type, recurrence_pattern, recurrence_anchor, priority,"
                " estimated_duration_minutes, deadline_offset_minutes, reminder_offsets_minutes, archived,"
                " created_at, updated_at, version) VALUES (?, 'x', ?, 'daily', 'calendar', 2, 30, ?, '[]', 0, ?, ?, 1)",
                (template_id, type_, offset, ts, ts),
            )
        for instance_id, template_id, type_, scheduled, deadline in (
            ("i-flex", "t-flex", "flexible", None, "2026-03-10 14:00:00.000000"),
            ("i-fixed", "t-fixed", "fixed", "2026-03-05 23:00:00.000000", None),
        ):
            conn.execute(
                "INSERT INTO task_instances (id, template_id, name, type, priority, estimated_duration_minutes, detached,"
                " scheduled_time, deadline, status, status_history, generated_at, created_at, updated_at, version)"
                " VALUES (?, ?, 'x', ?, 2, 30, 0, ?, ?, 'scheduled', '[]', ?, ?, ?, 1)",
                (instance_id, template_id, type_, scheduled, deadline, ts, ts, ts),
            )

    _run_alembic("upgrade", "head", database_path=db_path)

    with sqlite3.connect(db_path) as conn:
        nominal = dict(conn.execute("SELECT id, nominal_date FROM task_instances").fetchall())
    assert nominal["i-flex"].startswith("2026-03-09 14:00:00")  # deadline minus one day
    assert nominal["i-fixed"].startswith("2026-03-05 23:00:00")  # scheduled_time
