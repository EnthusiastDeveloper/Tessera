"""auth: sessions and admin password reset marker

Revision ID: e1422bae3900
Revises: a4e50b14830f
Create Date: 2026-08-08 16:37:01.808013

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "e1422bae3900"
down_revision: str | None = "a4e50b14830f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: autogenerate also proposed dropping and (only in downgrade()) recreating every
# existing Enum column's CHECK constraint - a false positive from how Alembic reflects
# SQLite check constraints back against the model, not a real schema change. Left out
# entirely here; the constraints added in the previous revision are untouched by this one.


def upgrade() -> None:
    op.create_table(
        "admin_password_reset_marker",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("consumed_value_hash", sa.String(), nullable=False),
        sa.Column("consumed_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("admin_password_reset_marker")
