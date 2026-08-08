"""ORM models for every design doc §3 entity. Importing this package populates `Base.metadata`
fully, which is what Alembic autogenerate and `Base.metadata.create_all()` rely on.
"""

from app.db.models.admin_password_reset_marker import AdminPasswordResetMarkerORM
from app.db.models.external_calendar_connection import ExternalCalendarConnectionORM
from app.db.models.external_event import ExternalEventORM
from app.db.models.notification import NotificationORM
from app.db.models.session import SessionORM
from app.db.models.task_instance import TaskInstanceORM, task_instance_dependencies
from app.db.models.task_template import TaskTemplateORM
from app.db.models.user import UserORM
from app.db.models.user_settings import UserSettingsORM

__all__ = [
    "AdminPasswordResetMarkerORM",
    "ExternalCalendarConnectionORM",
    "ExternalEventORM",
    "NotificationORM",
    "SessionORM",
    "TaskInstanceORM",
    "TaskTemplateORM",
    "UserORM",
    "UserSettingsORM",
    "task_instance_dependencies",
]
