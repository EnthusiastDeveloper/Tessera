"""Repository for `Notification` rows. See design doc §3.4, §3.9, §5."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.notification import NotificationORM
from app.db.schemas import Notification, NotificationType


class NotificationRepository:
    """CRUD plus the instance-scoped lookup §3.9's auto-resolution scan needs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, notification: Notification) -> Notification:
        orm = NotificationORM(**_to_orm_kwargs(notification))
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, notification_id: str) -> Notification | None:
        orm = self._session.get(NotificationORM, notification_id)
        return _to_domain(orm) if orm is not None else None

    def list_for_instance(self, instance_id: str) -> tuple[Notification, ...]:
        """Every notification (any state) raised against `instance_id` - what §3.9 scans to auto-resolve."""
        stmt = select(NotificationORM).where(NotificationORM.related_instance_id == instance_id)
        return tuple(_to_domain(orm) for orm in self._session.scalars(stmt))

    def update(self, notification: Notification) -> Notification:
        orm = self._session.get(NotificationORM, notification.id)
        if orm is None:
            raise LookupError(f"Notification {notification.id} not found")
        for key, value in _to_orm_kwargs(notification).items():
            if key not in ("id", "created_at"):
                setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm)


def _to_orm_kwargs(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "type": notification.type,
        "related_instance_id": notification.related_instance_id,
        "message": notification.message,
        "created_at": notification.created_at,
        "dismissed_at": notification.dismissed_at,
        "resolved_at": notification.resolved_at,
    }


def _to_domain(orm: NotificationORM) -> Notification:
    return Notification(
        id=orm.id,
        type=cast(NotificationType, orm.type),
        related_instance_id=orm.related_instance_id,
        message=orm.message,
        created_at=orm.created_at,
        dismissed_at=orm.dismissed_at,
        resolved_at=orm.resolved_at,
    )
