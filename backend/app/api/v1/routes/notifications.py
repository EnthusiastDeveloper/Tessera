"""Notification endpoints. See design doc §3.4, §5, §8.1 item 5; architecture-plan §3."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.dependencies import DB_SESSION
from app.api.errors import AppError
from app.db.schemas import Notification
from app.notifications import service

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
def list_notifications_endpoint(db: Session = DB_SESSION) -> list[Notification]:
    """Undismissed and unresolved - the Notifications panel (§8.1 item 5)."""
    return list(service.list_active(db))


@router.post("/{notification_id}/dismiss")
def dismiss_notification_endpoint(notification_id: str, db: Session = DB_SESSION) -> Notification:
    try:
        return service.dismiss(db, notification_id)
    except service.NotificationNotFoundError as exc:
        raise AppError.for_code("not_found", str(exc)) from exc
