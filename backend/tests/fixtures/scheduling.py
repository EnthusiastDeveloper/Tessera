"""Shared test builders for scheduling_engine tests.

Design doc §10 states every Worked Example uses timezone America/New_York and
local times - these helpers exist so every test constructs fixtures the same way
rather than re-deriving tzinfo/parsing boilerplate per test file.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.scheduling_engine.types import DAY_NAMES, ActiveHoursMap, ActiveHoursWindow

NY = ZoneInfo("America/New_York")


def ny(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """A tz-aware America/New_York datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=NY)


def ny_date(year: int, month: int, day: int) -> date:
    return date(year, month, day)


def hm(text: str) -> time:
    """Parse "HH:MM" into a time, matching the design doc's wall-clock string fields."""
    hour, minute = text.split(":")
    return time(int(hour), int(minute))


def window(start: str, end: str) -> ActiveHoursWindow:
    return ActiveHoursWindow(start=hm(start), end=hm(end))


def every_day(start: str, end: str) -> ActiveHoursMap:
    """An active-hours map with the identical window on all seven days (e.g. Examples B, E, I)."""
    return dict.fromkeys(DAY_NAMES, window(start, end))


def no_budget() -> dict[str, int | None]:
    """A daily_time_budget_minutes map with every day unlimited."""
    return dict.fromkeys(DAY_NAMES, None)


def local_today(timezone: str = "America/New_York") -> date:
    """Today in `timezone` by the template service's clock - the earliest `start_date` a
    template may take (§3.2). Reads the clock through the service module so a test that
    pins `utcnow` there gets its pinned day."""
    from app.task_templates import service

    return service.utcnow().astimezone(ZoneInfo(timezone)).date()


def app_today() -> date:
    """Today in the timezone the API tests' app seeds its settings with (the `TZ` env)."""
    import os

    from app.settings.service import default_timezone_from_env

    return local_today(default_timezone_from_env(os.getenv("TZ")))
