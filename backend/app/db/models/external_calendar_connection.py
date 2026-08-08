"""ORM model for `ExternalCalendarConnection`. See design doc §3.5."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, generate_id


class ExternalCalendarConnectionORM(Base):
    """A read-only external calendar link. See §3.5 - POC never writes back to the provider."""

    __tablename__ = "external_calendar_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    # `create_constraint=True` on every `Enum` here: SQLAlchemy 2.0 defaults it to False -
    # see task_template.py's note.
    provider: Mapped[str] = mapped_column(
        Enum("google", "outlook", "other", name="calendar_provider", create_constraint=True), nullable=False
    )
    oauth_credentials_ref: Mapped[str] = mapped_column(String, nullable=False)  # secret-store ref, not raw tokens
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sync_mode: Mapped[str] = mapped_column(
        Enum("read_only", name="sync_mode", create_constraint=True), nullable=False, default="read_only"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
