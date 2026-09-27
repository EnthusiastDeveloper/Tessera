"""schedule repairs

Revision ID: d91f3b6c2e84
Revises: c5a8e2f41d07
Create Date: 2026-09-27 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.base import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "d91f3b6c2e84"
down_revision: str | None = "c5a8e2f41d07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Design doc 6.10 (Rev 11), architecture-plan 5.2: progress of the background repair a
# stricter settings save starts.


def upgrade() -> None:
    op.create_table(
        "schedule_repairs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("moved", sa.Integer(), nullable=False),
        sa.Column("unschedulable", sa.Integer(), nullable=False),
        sa.Column("requested_at", UTCDateTime(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedule_repairs_requested_at", "schedule_repairs", ["requested_at"])


def downgrade() -> None:
    op.drop_index("ix_schedule_repairs_requested_at", table_name="schedule_repairs")
    op.drop_table("schedule_repairs")
