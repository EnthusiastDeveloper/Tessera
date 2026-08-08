"""ORM model for the `RESET_ADMIN_PASSWORD` one-time-consumption marker. See design doc §3.6.

"The marker is stored as a row in the database, not as a file. A marker written to the
container's writable layer is erased on every container recreate, at which point the env
var becomes exactly the standing backdoor this mechanism exists to prevent." Singleton in
practice, like `UserSettingsORM` - `AdminPasswordResetMarkerRepository` owns that access
pattern.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, generate_id


class AdminPasswordResetMarkerORM(Base):
    """Records the hash of the last `RESET_ADMIN_PASSWORD` value consumed, so a value left
    in place across a restart is not silently re-applied (design doc §3.6).
    """

    __tablename__ = "admin_password_reset_marker"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    consumed_value_hash: Mapped[str] = mapped_column(String, nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
