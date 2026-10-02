"""task template start_date

Revision ID: c5a8e2f41d07
Revises: b7d2c41e9a10
Create Date: 2026-09-27 10:00:00.000000

"""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op
from app.db.base import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "c5a8e2f41d07"
down_revision: str | None = "b7d2c41e9a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Design doc Revision 10 (§3.2): a template records the local date its series starts
# from. Existing templates are backfilled with the local date of their earliest
# occurrence, falling back to the day they were created - the date the old code
# effectively started them from.

_templates = sa.table(
    "task_templates",
    sa.column("id", sa.String),
    sa.column("created_at", UTCDateTime()),
    sa.column("start_date", sa.Date),
)
_instances = sa.table(
    "task_instances",
    sa.column("template_id", sa.String),
    sa.column("nominal_date", UTCDateTime()),
)
_settings = sa.table("user_settings", sa.column("timezone", sa.String))


def upgrade() -> None:
    with op.batch_alter_table("task_templates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("start_date", sa.Date(), nullable=True))

    bind = op.get_bind()
    timezone = bind.execute(sa.select(_settings.c.timezone)).scalar() or "UTC"
    tz = ZoneInfo(timezone)
    earliest: dict[str, datetime] = {}
    for template_id, nominal in bind.execute(sa.select(_instances.c.template_id, _instances.c.nominal_date)).all():
        if nominal is not None and (template_id not in earliest or nominal < earliest[template_id]):
            earliest[template_id] = nominal
    for row in bind.execute(sa.select(_templates.c.id, _templates.c.created_at)).all():
        first = earliest.get(row.id)
        moment = first or row.created_at
        if moment is None:
            continue
        bind.execute(sa.update(_templates).where(_templates.c.id == row.id).values(start_date=moment.astimezone(tz).date()))


def downgrade() -> None:
    with op.batch_alter_table("task_templates", schema=None) as batch_op:
        batch_op.drop_column("start_date")
