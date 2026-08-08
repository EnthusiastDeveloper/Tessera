"""ORM model for the server-side session table. See architecture-plan §6 ("Session storage").

Not one of design doc §3's seven entities - a new table architecture-plan §6 requires
explicitly: "Server-side session table in SQLite + signed cookie. Row: high-entropy id,
user_id, created_at, expires_at."
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class SessionORM(Base):
    """A logged-in session. `id` is the high-entropy token issued to the client (§6.1)."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
