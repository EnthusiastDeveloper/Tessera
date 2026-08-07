"""Placement grid math. See design doc §6.2 'Placement grid' and §6.8.

Computed start times land on a 15-minute grid aligned to the hour (:00, :15, :30,
:45) in local wall-clock time. The grid constrains computed starts only - durations
and budgets stay exact, unquantised minutes (§6.2).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.scheduling_engine.types import ActiveHoursWindow

DEFAULT_GRID_MINUTES = 15

# A fixed synthetic date for combining bare `time`-of-day values into `datetime`
# objects so `ceil_to_grid` (which operates on `datetime`) can be reused for
# time-of-day-only math. The date itself is arbitrary and never observed by callers.
_REFERENCE_DAY = date(2000, 1, 1)


def ceil_to_grid(moment: datetime, grid_minutes: int = DEFAULT_GRID_MINUTES) -> datetime:
    """Round `moment` up to the next hour-aligned grid point (§6.2).

    A `moment` that already lands exactly on a grid point is returned unchanged.
    """
    floor_minute = (moment.minute // grid_minutes) * grid_minutes
    floor_point = moment.replace(minute=floor_minute, second=0, microsecond=0)
    # floor_point can never be later than moment - it's built by flooring moment's
    # own minute/second/microsecond - so this is an equality check, not a range.
    if floor_point == moment:
        return floor_point
    return floor_point + timedelta(minutes=grid_minutes)


def usable_minutes(window: ActiveHoursWindow, grid_minutes: int = DEFAULT_GRID_MINUTES) -> int:
    """Minutes of `window` usable for placement, measured from the first grid point at/after start (§6.8).

    This is deliberately *not* `end - start`: a task can only ever be placed
    starting on a grid point, so a window whose start isn't grid-aligned (e.g.
    18:07) is effectively shorter than its raw span for feasibility purposes.
    Built on `ceil_to_grid` rather than re-deriving the rounding rule, so the two
    can't drift apart as that rule evolves.
    """
    grid_start = ceil_to_grid(datetime.combine(_REFERENCE_DAY, window.start), grid_minutes)
    window_end = datetime.combine(_REFERENCE_DAY, window.end)
    return max(0, int((window_end - grid_start).total_seconds() // 60))
