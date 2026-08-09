"""ORM model for encrypted OAuth token storage. See design doc §3.5, architecture-plan §6.

`ExternalCalendarConnection.oauth_credentials_ref` points at a row here by id - never at
raw tokens in the connection table itself. Column values are Fernet ciphertext produced by
`app.calendar_sync.token_crypto`; this layer never sees or handles plaintext.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, generate_id


class OAuthTokenORM(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    encrypted_access_token: Mapped[str] = mapped_column(String, nullable=False)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    access_token_expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
