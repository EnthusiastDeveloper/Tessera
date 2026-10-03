"""active hours become a list of windows per day

Revision ID: a2b7e5c19d36
Revises: f4a1c7d93b52
Create Date: 2026-10-03 15:00:00.000000

"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b7e5c19d36"
down_revision: str | None = "f4a1c7d93b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Design doc Revision 13 (§3.7): a day holds a LIST of windows, and a window whose end is
# before its start runs overnight. `user_settings.active_hours` and
# `task_templates.active_hours_override` are JSON maps `{day: {start, end} | null}`; each
# single window becomes a one-item list. A window that never had any length (`end` not after
# `start`) placed nothing under the old rules, and under the new ones would read as an
# overnight window - so it becomes `null` (the day excluded), which behaves exactly as it did.

_user_settings = sa.table("user_settings", sa.column("id", sa.String), sa.column("active_hours", sa.JSON))
_templates = sa.table("task_templates", sa.column("id", sa.String), sa.column("active_hours_override", sa.JSON))


def _forward(mapping: dict[str, Any] | None) -> dict[str, Any] | None:
    if mapping is None:
        return None
    converted: dict[str, Any] = {}
    for day, window in mapping.items():
        if window is None or isinstance(window, list):
            converted[day] = window
        elif window["end"] <= window["start"]:
            converted[day] = None
        else:
            converted[day] = [window]
    return converted


def _backward(mapping: dict[str, Any] | None) -> dict[str, Any] | None:
    """Lossy by nature: a single-window schema keeps only a day's first window, and an
    overnight window (which the old engine would have read as empty) becomes an excluded day."""
    if mapping is None:
        return None
    converted: dict[str, Any] = {}
    for day, windows in mapping.items():
        if not isinstance(windows, list):
            converted[day] = windows
            continue
        usable = [w for w in sorted(windows, key=lambda w: w["start"]) if w["end"] > w["start"]]
        converted[day] = usable[0] if usable else None
    return converted


def _rewrite(table: sa.TableClause, column: str, convert: Any) -> None:
    bind = op.get_bind()
    col = table.c[column]
    for row_id, raw in bind.execute(sa.select(table.c.id, col)).all():
        value = json.loads(raw) if isinstance(raw, str) else raw
        converted = convert(value)
        if converted != value:
            bind.execute(sa.update(table).where(table.c.id == row_id).values({column: converted}))


def upgrade() -> None:
    _rewrite(_user_settings, "active_hours", _forward)
    _rewrite(_templates, "active_hours_override", _forward)


def downgrade() -> None:
    _rewrite(_user_settings, "active_hours", _backward)
    _rewrite(_templates, "active_hours_override", _backward)
