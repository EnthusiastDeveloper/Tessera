"""task instance nominal_date

Revision ID: b7d2c41e9a10
Revises: e03f2aeaad85
Create Date: 2026-09-24 17:00:00.000000

"""

from collections.abc import Sequence
from datetime import timedelta

import sqlalchemy as sa

from alembic import op
from app.db.base import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "b7d2c41e9a10"
down_revision: str | None = "e03f2aeaad85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Each instance's nominal date (design doc §9.1) used to be re-derived from fields a
# this-occurrence edit can change - `deadline - deadline_offset_minutes` for flexible,
# the date of `scheduled_time` for fixed - so one occurrence's override shifted every
# later occurrence of its series. It is now stored once, at generation.
#
# The backfill reproduces exactly what the old derivation produced, so existing series
# keep the dates they would have had; only overrides made from now on stop leaking.

_instances = sa.table(
    "task_instances",
    sa.column("id", sa.String),
    sa.column("template_id", sa.String),
    sa.column("type", sa.String),
    sa.column("scheduled_time", UTCDateTime()),
    sa.column("deadline", UTCDateTime()),
    sa.column("nominal_date", UTCDateTime()),
)
_templates = sa.table("task_templates", sa.column("id", sa.String), sa.column("deadline_offset_minutes", sa.Integer))


def upgrade() -> None:
    with op.batch_alter_table("task_instances", schema=None) as batch_op:
        batch_op.add_column(sa.Column("nominal_date", UTCDateTime(), nullable=True))

    bind = op.get_bind()
    offsets = {row.id: row.deadline_offset_minutes or 0 for row in bind.execute(sa.select(_templates))}
    for row in bind.execute(sa.select(_instances)).all():
        if row.type == "flexible" and row.deadline is not None:
            nominal = row.deadline - timedelta(minutes=offsets.get(row.template_id, 0))
        elif row.type == "fixed" and row.scheduled_time is not None:
            nominal = row.scheduled_time
        else:
            continue
        bind.execute(sa.update(_instances).where(_instances.c.id == row.id).values(nominal_date=nominal))


def downgrade() -> None:
    with op.batch_alter_table("task_instances", schema=None) as batch_op:
        batch_op.drop_column("nominal_date")
