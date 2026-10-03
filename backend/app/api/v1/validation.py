"""Field validation limits for the request bodies (design doc §3.13, IRR-2 M11).

One table, one place: the API models, the frontend's form constraints and the design doc's
validation table all quote these numbers. A violation is a `422 validation_error` from
Pydantic, in the standard error envelope.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.db.schemas import ActiveHoursWindow

MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
MAX_LOCATION_LENGTH = 200
MAX_DURATION_MINUTES = 24 * 60
MAX_RECURRENCE_INTERVAL = 365
MAX_DEADLINE_OFFSET_MINUTES = 365 * 24 * 60
MAX_REMINDER_OFFSETS = 10
MAX_REMINDER_OFFSET_MINUTES = 30 * 24 * 60
MAX_DAILY_BUDGET_MINUTES = 24 * 60
MAX_BLACKOUT_LABEL_LENGTH = 100
MAX_WINDOWS_PER_DAY = 8

#: 24-hour wall-clock "HH:MM", 00:00-23:59.
CLOCK_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH)]
Description = Annotated[str, StringConstraints(max_length=MAX_DESCRIPTION_LENGTH)]
Location = Annotated[str, StringConstraints(max_length=MAX_LOCATION_LENGTH)]
DurationMinutes = Annotated[int, Field(ge=1, le=MAX_DURATION_MINUTES)]
RecurrenceInterval = Annotated[int, Field(ge=1, le=MAX_RECURRENCE_INTERVAL)]
DayOfWeek = Annotated[int, Field(ge=0, le=6)]
DayOfMonth = Annotated[int, Field(ge=1, le=31)]
DeadlineOffsetMinutes = Annotated[int, Field(ge=1, le=MAX_DEADLINE_OFFSET_MINUTES)]
ClockTime = Annotated[str, StringConstraints(pattern=CLOCK_TIME_PATTERN)]


ReminderOffsets = Annotated[
    tuple[Annotated[int, Field(ge=0, le=MAX_REMINDER_OFFSET_MINUTES)], ...],
    Field(max_length=MAX_REMINDER_OFFSETS),
]
#: One day's list of active-hours windows (design doc 3.7, Rev 13): never empty - a day with no
#: windows is `null` - and at most eight. Zero-length and overlapping windows are the service's check.
DayWindows = Annotated[list[ActiveHoursWindow], Field(min_length=1, max_length=MAX_WINDOWS_PER_DAY)]
DailyBudgetMinutes = Annotated[int, Field(ge=0, le=MAX_DAILY_BUDGET_MINUTES)]
