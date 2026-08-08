"""cascade-delete notifications with their task instance

Revision ID: a880890c42ea
Revises: e1422bae3900
Create Date: 2026-08-08 22:39:50.925978

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a880890c42ea"
down_revision: str | None = "e1422bae3900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: autogenerate also proposed dropping every existing Enum column's CHECK constraint
# across four unrelated tables - the same false positive already documented in
# e1422bae3900. Left out entirely; batch_alter_table's recreate preserves
# notifications.notification_type's own CHECK constraint on its own since only the
# foreign key is touched below.
#
# The real change: `notifications.related_instance_id` had no ON DELETE behavior, so
# deleting a TaskInstance with any unresolved notification (overdue, unschedulable, ...)
# hard-failed with a bare FK error - found via Stage 6's real job scheduler actually
# firing one mid-test, not by inspection. A Notification has no meaning once its instance
# is gone (contrast task_instance_dependencies' deliberate unlink-not-cascade for
# dependency edges, design doc §3.8), so this cascades.


# SQLite never names foreign keys unless the model does, so Alembic's batch mode can't
# `drop_constraint(None, ...)` against a reflected table without a naming_convention to
# compute a deterministic name to match against - a well-known Alembic+SQLite gotcha.
_FK_NAMING_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
_FK_NAME = "fk_notifications_related_instance_id_task_instances"


def upgrade() -> None:
    with op.batch_alter_table("notifications", schema=None, naming_convention=_FK_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
        batch_op.create_foreign_key(_FK_NAME, "task_instances", ["related_instance_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    with op.batch_alter_table("notifications", schema=None, naming_convention=_FK_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
        batch_op.create_foreign_key(_FK_NAME, "task_instances", ["related_instance_id"], ["id"])
