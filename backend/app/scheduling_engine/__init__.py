"""Pure scheduling engine. See design doc §6.

Zero imports of FastAPI, SQLAlchemy, or anything under `app/` (architecture-plan
§2) - enforced by `.importlinter`'s "Scheduling engine stays pure" contract and by
`tests/architecture/test_scheduling_engine_imports.py`. Every function here is
framework-agnostic and deterministic: no DB, no HTTP, no hidden `now()`.
"""

from app.scheduling_engine.calendar_rules import day_name, day_range, is_blacked_out, merge_active_hours
from app.scheduling_engine.deadlines import is_deadline_elapsed
from app.scheduling_engine.dependencies import cycle_check
from app.scheduling_engine.feasibility import validate_feasible_duration
from app.scheduling_engine.fixed_conflicts import check_fixed_conflict
from app.scheduling_engine.grid import ceil_to_grid, usable_minutes
from app.scheduling_engine.placement import find_first_free_slot, schedule_pending_flexible_tasks
from app.scheduling_engine.types import (
    DAY_NAMES,
    ActiveHoursMap,
    ActiveHoursWindow,
    BlackoutDate,
    BudgetEnforcement,
    FlexibleTaskCandidate,
    Obstacle,
    Placement,
    SchedulingResult,
)

__all__ = [
    "DAY_NAMES",
    "ActiveHoursMap",
    "ActiveHoursWindow",
    "BlackoutDate",
    "BudgetEnforcement",
    "FlexibleTaskCandidate",
    "Obstacle",
    "Placement",
    "SchedulingResult",
    "ceil_to_grid",
    "check_fixed_conflict",
    "cycle_check",
    "day_name",
    "day_range",
    "find_first_free_slot",
    "is_blacked_out",
    "is_deadline_elapsed",
    "merge_active_hours",
    "schedule_pending_flexible_tasks",
    "usable_minutes",
    "validate_feasible_duration",
]
