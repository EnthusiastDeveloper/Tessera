"""Recurring instance generation. See design doc §9.1.

Reads the template's CURRENT values and (for `anchor: "completion"`) the just-completed
predecessor's completion instant; returns the next instance's field values. Never reads a
predecessor's own overridden fields (name/duration/etc.) - "detached is a property of an
instance, not of the template" (§9.1, Rev 7) - so a "this occurrence" override never
leaks into the next generated instance. The predecessor is consulted only to advance the
recurrence rule (its nominal date, for `calendar` anchor) or its completion instant (for
`completion` anchor) - never its content fields.

The completion-triggered *call* to this function (instance reaches `completed` -> call
this -> persist the result) is Stage 6's job (implementation-plan Stage 5 "Out of scope");
this stage builds the function itself, called directly at template-creation time for the
first instance and by tests for the regression guard.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.db.schemas import Priority, TaskInstance, TaskTemplate, TaskType

# Numeric priority mapping is internal-only (§3.2 notes) - duplicated from
# app.db.repositories.task_template_repository's private copy rather than imported,
# since app.scheduling must not depend on app.db.repositories internals and this is a
# tiny, stable 4-entry constant, not real logic to keep in sync.
_PRIORITY_TO_INT: dict[Priority, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class GeneratedInstanceFields:
    """The next instance's computed fields. The caller still owns id generation, the §6.7
    missed-gate check, and persistence - this is pure field computation only.
    """

    name: str
    description: str | None
    location: str | None
    type: TaskType
    priority: int
    estimated_duration_minutes: int
    scheduled_time: datetime | None  # set for fixed templates only
    deadline: datetime | None  # set for flexible templates only
    nominal_date: datetime  # earliest-start gate for completion anchor (§9.1); informational for calendar anchor


def generate_next_instance(
    template: TaskTemplate,
    *,
    predecessor: TaskInstance | None,
    now: datetime,
    timezone: str,
) -> GeneratedInstanceFields:
    """`predecessor` is the template's most recent instance - for `anchor: "completion"`
    it must be `completed` (its `completed_at` anchors the next nominal date); for
    `anchor: "calendar"` any terminal or non-terminal instance works, since only its
    nominal date is read. `None` only for a template's very first instance, at creation.
    """
    tz = ZoneInfo(timezone)
    nominal = _next_nominal_instant(template, predecessor=predecessor, now=now, tz=tz)

    scheduled_time: datetime | None = None
    deadline: datetime | None = None
    if template.type == "fixed":
        scheduled_time = project_fixed_time(nominal.date(), template=template, tz=tz)
    else:
        deadline = nominal + timedelta(minutes=template.deadline_offset_minutes or 0)

    return GeneratedInstanceFields(
        name=template.name,
        description=template.description,
        location=template.location,
        type=template.type,
        priority=_PRIORITY_TO_INT[template.priority],
        estimated_duration_minutes=template.estimated_duration_minutes,
        scheduled_time=scheduled_time,
        deadline=deadline,
        nominal_date=nominal,
    )


def _next_nominal_instant(template: TaskTemplate, *, predecessor: TaskInstance | None, now: datetime, tz: ZoneInfo) -> datetime:
    pattern = template.recurrence.pattern

    if predecessor is None:
        # The template's very first instance: project the rule forward from "now".
        # one_time has no rule to project - it simply starts now.
        if pattern == "one_time":
            return now.astimezone(tz)
        return _advance(pattern, template, after=now.astimezone(tz), tz=tz)

    if template.recurrence.anchor == "completion":
        if predecessor.completed_at is None:
            raise ValueError("completion-anchored generation requires a completed predecessor")
        base = predecessor.completed_at.astimezone(tz)
    else:
        base = _predecessor_nominal_date(predecessor, template, tz=tz)

    return _advance(pattern, template, after=base, tz=tz)


def _predecessor_nominal_date(predecessor: TaskInstance, template: TaskTemplate, *, tz: ZoneInfo) -> datetime:
    """The predecessor's own nominal instant - never its overridden content fields.

    Flexible: `deadline - deadline_offset_minutes` (design doc's own relationship for
    the completion-anchor case, reused here as the general definition). Fixed: the date
    part of `scheduled_time` combined with the template's *current* `fixed_time_of_day`
    (never the predecessor's own `scheduled_time` hour/minute, which may itself be a
    "this occurrence" override - see the module docstring).
    """
    if predecessor.type == "flexible":
        if predecessor.deadline is None:
            raise ValueError(f"flexible predecessor {predecessor.id} has no deadline")
        offset = template.deadline_offset_minutes or 0
        return predecessor.deadline.astimezone(tz) - timedelta(minutes=offset)
    if predecessor.scheduled_time is None:
        raise ValueError(f"fixed predecessor {predecessor.id} has no scheduled_time")
    return project_fixed_time(predecessor.scheduled_time.astimezone(tz).date(), template=template, tz=tz)


def project_fixed_time(nominal_date: date, *, template: TaskTemplate, tz: ZoneInfo) -> datetime:
    """Wall-clock `fixed_time_of_day` re-projected against the *current* timezone (§14.1) -
    never a stored UTC instant, so a later timezone-setting change re-projects correctly.
    """
    if template.fixed_time_of_day is None:
        raise ValueError(f"fixed template {template.id} has no fixed_time_of_day")
    hour, minute = template.fixed_time_of_day.split(":")
    return datetime.combine(nominal_date, time(int(hour), int(minute)), tzinfo=tz)


def _advance(pattern: str, template: TaskTemplate, *, after: datetime, tz: ZoneInfo) -> datetime:
    interval = template.recurrence.interval or 1

    if pattern == "daily":
        return after + timedelta(days=interval)

    if pattern == "weekly":
        target_weekday = template.recurrence.day_of_week
        if target_weekday is None:
            return after + timedelta(weeks=interval)
        return _next_weekday_on_or_after(after + timedelta(days=1), target_weekday, tz=tz)

    if pattern == "monthly":
        day_of_month = template.recurrence.day_of_month or after.day
        return _add_months(after, interval, day_of_month=day_of_month, tz=tz)

    if pattern == "custom":
        # Not elaborated anywhere in the source docs beyond the field existing - treated
        # as "every `interval` days", the same simplification as `daily`, documented here
        # rather than silently guessed at a second time somewhere else.
        return after + timedelta(days=interval)

    raise ValueError(f"cannot advance a one_time template's recurrence (pattern={pattern!r})")


def _next_weekday_on_or_after(moment: datetime, target_weekday: int, *, tz: ZoneInfo) -> datetime:
    days_ahead = (target_weekday - moment.weekday()) % 7
    result_date = moment.date() + timedelta(days=days_ahead)
    return datetime.combine(result_date, moment.time(), tzinfo=tz)


def _add_months(moment: datetime, months: int, *, day_of_month: int, tz: ZoneInfo) -> datetime:
    total_month_index = moment.month - 1 + months
    year = moment.year + total_month_index // 12
    month = total_month_index % 12 + 1
    last_day_of_month = monthrange(year, month)[1]
    day = min(day_of_month, last_day_of_month)
    return datetime.combine(date(year, month, day), moment.time(), tzinfo=tz)


__all__ = ["GeneratedInstanceFields", "generate_next_instance", "project_fixed_time"]
