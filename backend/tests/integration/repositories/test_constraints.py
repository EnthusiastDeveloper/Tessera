"""DB-level constraint tests. See implementation-plan Stage 2 "Tests required":
invalid enum rejected, required-field omission rejected.

These bypass the ORM's own client-side validation (SQLAlchemy's `Enum` type already
rejects an out-of-set Python value before a statement is even built) by executing raw SQL
directly, so what's actually under test is the schema's own CHECK/NOT NULL constraints -
the thing implementation-plan Stage 2 calls out by name ("status/type as string enums
with DB-level constraints").
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.models.task_template import TaskTemplateORM


def test_invalid_enum_value_is_rejected_at_db_level(db_session: Session) -> None:
    """`type` is declared `Enum("fixed", "flexible", ...)` - SQLite renders that as a CHECK constraint."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO task_templates (
                    id, name, type, recurrence_pattern, recurrence_anchor,
                    priority, estimated_duration_minutes, reminder_offsets_minutes,
                    archived, created_at, updated_at, version
                ) VALUES (
                    :id, :name, :type, :recurrence_pattern, :recurrence_anchor,
                    :priority, :estimated_duration_minutes, :reminder_offsets_minutes,
                    :archived, :created_at, :updated_at, :version
                )
                """
            ),
            {
                "id": "bad-enum-1",
                "name": "Bad",
                "type": "bogus",  # not "fixed" or "flexible"
                "recurrence_pattern": "one_time",
                "recurrence_anchor": "calendar",
                "priority": 1,
                "estimated_duration_minutes": 10,
                "reminder_offsets_minutes": "[]",
                "archived": 0,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "version": 1,
            },
        )


def test_missing_required_field_is_rejected_at_db_level(db_session: Session) -> None:
    """`name` is NOT NULL with no default - constructed directly via the ORM to bypass Pydantic entirely."""
    orm = TaskTemplateORM(
        id=generate_id(),
        type="flexible",
        recurrence_pattern="one_time",
        recurrence_anchor="calendar",
        priority=1,
        estimated_duration_minutes=10,
        created_at=utcnow(),
        updated_at=utcnow(),
        version=1,
    )
    db_session.add(orm)
    with pytest.raises(IntegrityError):
        db_session.flush()
