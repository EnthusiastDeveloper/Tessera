"""Unit tests for app.scheduling_engine.feasibility.validate_feasible_duration. See design doc §6.8."""

from app.scheduling_engine.feasibility import validate_feasible_duration
from tests.fixtures.scheduling import every_day, window


def test_example_i_feasibility_hard_block() -> None:
    # active_hours every day 18:00-21:00 (180 min); a 300-minute task can never fit.
    effective = every_day("18:00", "21:00")
    assert validate_feasible_duration(300, effective) is False


def test_example_i_grid_variant() -> None:
    # 18:07-21:00 usable from the first grid point (18:15) -> 165 minutes, not 173.
    effective = every_day("18:07", "21:00")
    assert validate_feasible_duration(170, effective) is False
    assert validate_feasible_duration(165, effective) is True


def test_example_e_duration_fits_some_day() -> None:
    # 150-minute task against a 180-minute window: save succeeds (placement may
    # still fail later per Example E - that is a separate, non-feasibility concern).
    effective = every_day("18:00", "21:00")
    assert validate_feasible_duration(150, effective) is True


def test_exact_boundary_duration_is_feasible() -> None:
    effective = every_day("18:00", "21:00")
    assert validate_feasible_duration(180, effective) is True


def test_one_minute_over_boundary_is_infeasible() -> None:
    effective = every_day("18:00", "21:00")
    assert validate_feasible_duration(181, effective) is False


def test_no_non_null_day_at_all_is_infeasible() -> None:
    effective = dict.fromkeys(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"], None)
    assert validate_feasible_duration(10, effective) is False


def test_empty_map_is_infeasible() -> None:
    assert validate_feasible_duration(10, {}) is False


def test_picks_the_largest_usable_window_across_days() -> None:
    effective = {
        "monday": window("18:00", "19:00"),  # 60 usable minutes
        "saturday": window("09:00", "21:00"),  # 720 usable minutes
    }
    assert validate_feasible_duration(600, effective) is True
    assert validate_feasible_duration(721, effective) is False
