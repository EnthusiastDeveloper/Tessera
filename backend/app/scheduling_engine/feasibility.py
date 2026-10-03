"""Creation-time feasibility validation for flexible tasks. See design doc §6.8.

Before a flexible TaskTemplate (and its initial instance) is saved, its
`estimated_duration_minutes` must fit within at least one day's effective
active-hours window - otherwise it would sit `pending` forever, re-triggering
`unschedulable` on every pass with no signal that the real problem is that the
task is structurally too big to ever fit as a single block.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.scheduling_engine.calendar_rules import eligible_intervals
from app.scheduling_engine.grid import DEFAULT_GRID_MINUTES, usable_minutes_between
from app.scheduling_engine.types import ActiveHoursMap

# A Monday, so the fortnight below starts on one; the date itself is never observed.
_REFERENCE_MONDAY = date(2001, 1, 1)


def validate_feasible_duration(
    estimated_duration_minutes: int,
    effective_active_hours_map: ActiveHoursMap,
    grid_minutes: int = DEFAULT_GRID_MINUTES,
) -> bool:
    """True if `estimated_duration_minutes` fits some stretch of usable time.

    A stretch is a window, or windows that run into each other (Monday's overnight window
    and Tuesday's morning one) - measured from its first grid point (§6.8).

    `effective_active_hours_map` must already be the MERGED map (see
    `calendar_rules.merge_active_hours`) - checking a template's override in
    isolation would reject tasks that are feasible against the combined map.
    """
    # Two reference weeks, so a window that runs overnight into the next day - or into the
    # next week, from Sunday - is joined with whatever follows it before being measured.
    stretches = eligible_intervals(
        _REFERENCE_MONDAY, _REFERENCE_MONDAY + timedelta(days=13), effective_active_hours_map, (), None
    )
    return estimated_duration_minutes <= max(
        (usable_minutes_between(start, end, grid_minutes) for start, end in stretches), default=0
    )
