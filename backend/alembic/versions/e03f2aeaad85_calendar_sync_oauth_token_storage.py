"""calendar sync: oauth token storage

Revision ID: e03f2aeaad85
Revises: a880890c42ea
Create Date: 2026-08-09 07:22:03.342174

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "e03f2aeaad85"
down_revision: str | None = "a880890c42ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: autogenerate also proposed dropping and (only in downgrade()) recreating every
# existing Enum column's CHECK constraint - the same false positive noted in
# e1422bae3900's migration, not a real schema change. Left out entirely here.


def upgrade() -> None:
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("encrypted_access_token", sa.String(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.String(), nullable=True),
        sa.Column("access_token_expires_at", UTCDateTime(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("oauth_tokens")
