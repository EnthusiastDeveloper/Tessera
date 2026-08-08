"""Notification service: list/dismiss. See design doc §3.4, §3.9, §5.

Creation and self-resolution happen at the trigger points that actually own them
(`app.scheduling.orchestration`, `app.task_instances.service`) - this module is only the
user-facing read/dismiss surface (§8.1 item 5's Notifications panel).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.repositories import NotificationRepository
from app.db.schemas import Notification


class NotificationNotFoundError(Exception):
    pass


def list_active(db: Session) -> tuple[Notification, ...]:
    return NotificationRepository(db).list_active()


def dismiss(db: Session, notification_id: str) -> Notification:
    """User explicitly closes it (§3.4). Works whether or not it already self-resolved -
    §3.9's "already resolved" state is a frontend display concern; the backend simply
    records the dismissal either way rather than rejecting it.
    """
    repo = NotificationRepository(db)
    notification = repo.get(notification_id)
    if notification is None:
        raise NotificationNotFoundError(f"Notification {notification_id} not found")
    return repo.update(notification.model_copy(update={"dismissed_at": utcnow()}))


__all__ = ["NotificationNotFoundError", "dismiss", "list_active"]
