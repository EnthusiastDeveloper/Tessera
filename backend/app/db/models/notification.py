"""ORM model for `Notification`. See design doc §3.4, §5."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, generate_id, utcnow


class NotificationORM(Base):
    """A distinct-from-status notice about a `TaskInstance`. See §3.4."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    type: Mapped[str] = mapped_column(
        Enum(
            "reminder",
            "creation_conflict",
            "sync_conflict",
            "unschedulable",
            "dependency_at_risk",
            "overdue",
            "budget_exceeded",
            "deadline_missed",
            name="notification_type",
            create_constraint=True,  # SQLAlchemy 2.0 defaults this to False - see task_template.py's note
        ),
        nullable=False,
    )
    related_instance_id: Mapped[str] = mapped_column(String, ForeignKey("task_instances.id"), nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    dismissed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
