"""ORM model for `ExternalEvent`. See design doc §3.11.

Locally cached copy of a provider event - the scheduling engine reads these rows as
plain obstacle data and never makes a network call (§3.11, §6.2). `(connection_id,
provider_event_id)` is unique so §6.4's sync diff is a plain upsert.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, generate_id


class ExternalEventORM(Base):
    """A cached external calendar event. See §3.11, §3.12 (retention: 90-day horizon, soft delete)."""

    __tablename__ = "external_events"
    __table_args__ = (UniqueConstraint("connection_id", "provider_event_id", name="uq_connection_provider_event"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    connection_id: Mapped[str] = mapped_column(
        String, ForeignKey("external_calendar_connections.id", ondelete="CASCADE"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String, nullable=False)

    start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)

    is_all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_transparent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # soft delete, §3.12
