"""Declarative base and shared column helpers for all ORM models. See design doc §3."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Shared declarative base - every ORM model in `app.db.models` inherits from this."""


def generate_id() -> str:
    """A random string primary key. Every design-doc §3 entity's `id` is `string`, not an int."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """The current instant, timezone-aware in UTC. See design doc §14.1 - never a naive datetime."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """A datetime column that is always timezone-aware UTC on the Python side.

    SQLite has no native tz-aware datetime type: plain `DateTime(timezone=True)` accepts
    an aware datetime on write but silently hands back a *naive* one on read - a
    long-standing SQLAlchemy+SQLite gap, not a hypothetical. Every persisted timestamp is
    UTC by design doc §14.1, so this type normalizes to UTC on the way in and re-attaches
    UTC tzinfo on the way out, rather than relying on every call site to remember it -
    the same "fix it once, centrally" reasoning as Stage 1's DST bug.
    """

    # `impl` is the *class*, not a pre-instantiated `DateTime(timezone=True)` - so that
    # `UTCDateTime()` is a valid, argument-free constructor call. Alembic's autogenerate
    # renders custom column types as a bare `UTCDateTime()` call (see `render_item` in
    # alembic/env.py); a pre-instantiated impl would reject that call with a TypeError.
    impl = DateTime
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("timezone", True)
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
