"""Builders for design doc §3 domain objects. Callers override only the fields under test."""

from __future__ import annotations

from typing import Any

from app.db.base import generate_id, utcnow
from app.db.schemas import (
    DayName,
    ExternalCalendarConnection,
    ExternalEvent,
    Notification,
    Recurrence,
    TaskInstance,
    TaskTemplate,
    User,
    UserSettings,
)

_DAY_NAMES: tuple[DayName, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
ALL_DAYS_OPEN = dict.fromkeys(_DAY_NAMES, {"start": "00:00", "end": "23:59"})
NO_BUDGET = dict.fromkeys(_DAY_NAMES, None)


def make_task_template(**overrides: Any) -> TaskTemplate:
    now = utcnow()
    defaults: dict[str, Any] = {
        "id": generate_id(),
        "name": "Water the plants",
        "type": "flexible",
        "recurrence": Recurrence(pattern="weekly", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 15,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskTemplate(**defaults)


def make_task_instance(*, template_id: str, **overrides: Any) -> TaskInstance:
    now = utcnow()
    defaults: dict[str, Any] = {
        "id": generate_id(),
        "template_id": template_id,
        "name": "Water the plants",
        "type": "flexible",
        "priority": 2,
        "estimated_duration_minutes": 15,
        "status": "pending",
        "generated_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskInstance(**defaults)


def make_notification(*, related_instance_id: str, **overrides: Any) -> Notification:
    defaults: dict[str, Any] = {
        "id": generate_id(),
        "type": "reminder",
        "related_instance_id": related_instance_id,
        "message": "Reminder: Water the plants",
        "created_at": utcnow(),
    }
    defaults.update(overrides)
    return Notification(**defaults)


def make_external_calendar_connection(**overrides: Any) -> ExternalCalendarConnection:
    defaults: dict[str, Any] = {
        "id": generate_id(),
        "provider": "google",
        "oauth_credentials_ref": "secret-ref-1",
        "refresh_interval_minutes": 15,
    }
    defaults.update(overrides)
    return ExternalCalendarConnection(**defaults)


def make_external_event(*, connection_id: str, **overrides: Any) -> ExternalEvent:
    now = utcnow()
    defaults: dict[str, Any] = {
        "id": generate_id(),
        "connection_id": connection_id,
        "provider_event_id": "evt-1",
        "start": now,
        "end": now,
        "title": "Dentist",
        "fetched_at": now,
    }
    defaults.update(overrides)
    return ExternalEvent(**defaults)


def make_user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "id": generate_id(),
        "username": "admin",
        "password_hash": "argon2id$fake-hash-for-tests",
        "created_at": utcnow(),
    }
    defaults.update(overrides)
    return User(**defaults)


def make_user_settings(**overrides: Any) -> UserSettings:
    defaults: dict[str, Any] = {
        "id": generate_id(),
        "timezone": "America/New_York",
        "active_hours": ALL_DAYS_OPEN,
        "daily_time_budget_minutes": NO_BUDGET,
    }
    defaults.update(overrides)
    return UserSettings(**defaults)
