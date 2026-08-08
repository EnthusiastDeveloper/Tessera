"""Pydantic domain schemas - the persisted shape of every design doc §3 entity.

These are what `app.db` repositories return and accept; they are **not** ORM models
(see `app.db.models`) and not API request/response models (Stage 8 may add separate
ones for partial-PATCH semantics, design doc §3.2/architecture-plan §5.1 - out of scope
here). Names and fields match the design doc's TypeScript interfaces exactly - this is
the traceability mechanism per architecture-plan §9, not just a convention.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

TaskType = Literal["fixed", "flexible"]
Priority = Literal["low", "medium", "high", "critical"]
RecurrencePattern = Literal["one_time", "daily", "weekly", "monthly", "custom"]
RecurrenceAnchor = Literal["calendar", "completion"]
TaskInstanceStatus = Literal["pending", "scheduled", "in_progress", "completed", "blocked", "missed", "dismissed"]
NotificationType = Literal[
    "reminder",
    "creation_conflict",
    "sync_conflict",
    "unschedulable",
    "dependency_at_risk",
    "overdue",
    "budget_exceeded",
    "deadline_missed",
]
CalendarProvider = Literal["google", "outlook", "other"]
BudgetEnforcement = Literal["strict", "soft"]
DayName = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ActiveHoursWindow(_Frozen):
    """A wall-clock scheduling window on a single day of week. See §3.7."""

    start: str  # "HH:MM"
    end: str


class Recurrence(_Frozen):
    """See §3.2. `anchor: "completion"` is valid only when the owning template is flexible."""

    pattern: RecurrencePattern
    interval: int | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    anchor: RecurrenceAnchor


class TaskTemplate(_Frozen):
    """See design doc §3.2."""

    id: str
    name: str
    description: str | None = None
    location: str | None = None
    type: TaskType
    recurrence: Recurrence
    fixed_time_of_day: str | None = None  # required if type == "fixed"
    deadline_offset_minutes: int | None = None  # required if type == "flexible"
    priority: Priority
    estimated_duration_minutes: int
    reminder_offsets_minutes: tuple[int, ...] = ()
    # A day named here uses that value (window, or null == excluded); a day not named
    # inherits UserSettings.active_hours (§3.2, §6.2). `None` means no override at all.
    active_hours_override: dict[DayName, ActiveHoursWindow | None] | None = None
    archived: bool = False
    created_at: datetime
    updated_at: datetime
    version: int


class StatusHistoryEntry(_Frozen):
    """One immutable row in a `TaskInstance`'s status trail. See §3.3."""

    status: TaskInstanceStatus
    at: datetime


class TaskInstance(_Frozen):
    """See design doc §3.3."""

    id: str
    template_id: str
    name: str
    description: str | None = None
    location: str | None = None
    type: TaskType
    priority: int  # numeric, copied from the template at generation
    estimated_duration_minutes: int
    detached: bool = False
    scheduled_time: datetime | None = None
    deadline: datetime | None = None
    status: TaskInstanceStatus
    status_history: tuple[StatusHistoryEntry, ...] = ()
    dependencies: tuple[str, ...] = ()  # TaskInstance ids this instance is waiting on
    completed_at: datetime | None = None
    generated_at: datetime
    created_at: datetime
    updated_at: datetime
    version: int


class Notification(_Frozen):
    """See design doc §3.4, §5."""

    id: str
    type: NotificationType
    related_instance_id: str
    message: str
    created_at: datetime
    dismissed_at: datetime | None = None
    resolved_at: datetime | None = None


class ExternalCalendarConnection(_Frozen):
    """See design doc §3.5. POC is read-only - `sync_mode` has one valid value."""

    id: str
    provider: CalendarProvider
    oauth_credentials_ref: str
    refresh_interval_minutes: int
    last_synced_at: datetime | None = None
    sync_mode: Literal["read_only"] = "read_only"
    enabled: bool = True


class User(_Frozen):
    """See design doc §3.6."""

    id: str
    username: str
    password_hash: str
    two_factor_enabled: bool = False
    created_at: datetime


class BlackoutDate(_Frozen):
    """A manual full-day exclusion range. See §3.7."""

    start: date
    end: date
    label: str | None = None


class UserSettings(_Frozen):
    """See design doc §3.7. Singleton in practice - see `UserSettingsRepository`."""

    id: str
    timezone: str
    active_hours: dict[DayName, ActiveHoursWindow | None]
    blackout_dates: tuple[BlackoutDate, ...] = ()
    daily_time_budget_minutes: dict[DayName, int | None]
    budget_enforcement: BudgetEnforcement = "soft"
    first_day_of_week: DayName = "monday"


class ExternalEvent(_Frozen):
    """See design doc §3.11. A locally cached copy of a provider event."""

    id: str
    connection_id: str
    provider_event_id: str
    start: datetime
    end: datetime
    title: str
    is_all_day: bool = False
    is_transparent: bool = False
    fetched_at: datetime
    deleted_at: datetime | None = None


__all__ = [
    "ActiveHoursWindow",
    "BlackoutDate",
    "BudgetEnforcement",
    "CalendarProvider",
    "DayName",
    "ExternalCalendarConnection",
    "ExternalEvent",
    "Notification",
    "NotificationType",
    "Priority",
    "Recurrence",
    "RecurrenceAnchor",
    "RecurrencePattern",
    "StatusHistoryEntry",
    "TaskInstance",
    "TaskInstanceStatus",
    "TaskTemplate",
    "TaskType",
    "User",
    "UserSettings",
]
