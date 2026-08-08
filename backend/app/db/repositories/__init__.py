"""Repository classes - one per design doc §3 aggregate. See architecture-plan §2.

Each repository converts to/from its ORM model (`app.db.models`) and returns/accepts
only `app.db.schemas` domain objects - ORM rows never leak past this layer.
"""

from app.db.repositories.external_calendar_connection_repository import ExternalCalendarConnectionRepository
from app.db.repositories.external_event_repository import ExternalEventRepository
from app.db.repositories.notification_repository import NotificationRepository
from app.db.repositories.task_instance_repository import TaskInstanceRepository
from app.db.repositories.task_template_repository import TaskTemplateRepository
from app.db.repositories.user_repository import UserRepository
from app.db.repositories.user_settings_repository import UserSettingsRepository

__all__ = [
    "ExternalCalendarConnectionRepository",
    "ExternalEventRepository",
    "NotificationRepository",
    "TaskInstanceRepository",
    "TaskTemplateRepository",
    "UserRepository",
    "UserSettingsRepository",
]
