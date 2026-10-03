"""drop the undefined `custom` recurrence pattern

Revision ID: f4a1c7d93b52
Revises: d91f3b6c2e84
Create Date: 2026-10-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a1c7d93b52"
down_revision: str | None = "d91f3b6c2e84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# IRR-2 M1: `custom` was in the enum with no definition and no configuring fields; the
# generator treated it as "every `interval` days", i.e. exactly `daily`. Existing rows are
# rewritten to `daily` (identical behaviour) before the value leaves the CHECK constraint.

_OLD = ("one_time", "daily", "weekly", "monthly", "custom")
_NEW = ("one_time", "daily", "weekly", "monthly")


def _pattern_enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="recurrence_pattern", create_constraint=True)


def upgrade() -> None:
    op.execute("UPDATE task_templates SET recurrence_pattern = 'daily' WHERE recurrence_pattern = 'custom'")
    with op.batch_alter_table("task_templates", schema=None) as batch_op:
        batch_op.alter_column(
            "recurrence_pattern",
            existing_type=_pattern_enum(_OLD),
            type_=_pattern_enum(_NEW),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("task_templates", schema=None) as batch_op:
        batch_op.alter_column(
            "recurrence_pattern",
            existing_type=_pattern_enum(_NEW),
            type_=_pattern_enum(_OLD),
            existing_nullable=False,
        )
