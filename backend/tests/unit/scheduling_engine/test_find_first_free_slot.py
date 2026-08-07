"""Unit tests for app.scheduling_engine.placement.find_first_free_slot (§6.2 Pass 1).

Examples B and C (placement half) are transcribed directly from design doc §10.
"""

from app.scheduling_engine.calendar_rules import merge_active_hours
from app.scheduling_engine.placement import find_first_free_slot
from app.scheduling_engine.types import DAY_NAMES, BlackoutDate, Obstacle
from tests.fixtures.scheduling import every_day, no_budget, ny, ny_date, window


def test_example_b_merged_override_and_grid_alignment() -> None:
    """Fails if active_hours_override is a whole-map replacement instead of a per-day merge."""
    global_hours = every_day("18:00", "21:00")
    override = {"tuesday": window("18:00", "22:30")}
    effective_hours = merge_active_hours(global_hours, override)

    obstacles = [
        Obstacle(start=ny(2026, 3, 2, 18, 0), end=ny(2026, 3, 2, 21, 0)),  # fills Monday's window
        Obstacle(start=ny(2026, 3, 3, 18, 0), end=ny(2026, 3, 3, 21, 37)),  # Tuesday, leaves a gap
    ]

    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=effective_hours,
        excluded_dates=[],
        daily_time_budget_minutes=no_budget(),
        obstacles=obstacles,
    )

    # First free moment is 21:37; first grid point at/after is 21:45. 21:45+30 <= 22:30.
    assert slot == ny(2026, 3, 3, 21, 45)


def test_example_c_placement_half_after_sync_eviction() -> None:
    """Continues Example B: a new Concert (21:00-23:00) collides with the scheduled slot.

    The evicted task's own former placement is no longer an obstacle (it's the
    task being re-placed); the original Tuesday external event is still there and,
    merged with the new Concert, now consumes the rest of Tuesday's window -
    forcing the placement onto Wednesday's plain (non-overridden) window instead.
    """
    global_hours = every_day("18:00", "21:00")
    override = {"tuesday": window("18:00", "22:30")}
    effective_hours = merge_active_hours(global_hours, override)

    obstacles = [
        Obstacle(start=ny(2026, 3, 2, 18, 0), end=ny(2026, 3, 2, 21, 0)),  # Monday, unrelated
        Obstacle(start=ny(2026, 3, 3, 18, 0), end=ny(2026, 3, 3, 21, 37)),  # Tuesday, pre-existing
        Obstacle(start=ny(2026, 3, 3, 21, 0), end=ny(2026, 3, 3, 23, 0)),  # Tuesday, new Concert
    ]

    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=effective_hours,
        excluded_dates=[],
        daily_time_budget_minutes=no_budget(),
        obstacles=obstacles,
    )

    # Wednesday's effective window ends at 21:00 (global), not 22:30 - the override named only Tuesday.
    assert slot == ny(2026, 3, 4, 18, 0)


def test_blackout_date_is_skipped_even_if_physically_free() -> None:
    effective_hours = every_day("18:00", "21:00")
    blackout = [BlackoutDate(start=ny_date(2026, 3, 2), end=ny_date(2026, 3, 2))]

    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=effective_hours,
        excluded_dates=blackout,
        daily_time_budget_minutes=no_budget(),
        obstacles=[],
    )

    assert slot == ny(2026, 3, 3, 18, 0)


def test_budget_skip_moves_to_the_next_eligible_day() -> None:
    effective_hours = every_day("18:00", "21:00")
    budget = no_budget()
    budget["monday"] = 50  # smaller than the 60-minute task -> Monday is skipped entirely, not partially considered

    slot = find_first_free_slot(
        duration_minutes=60,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=effective_hours,
        excluded_dates=[],
        daily_time_budget_minutes=budget,
        obstacles=[],
    )

    assert slot == ny(2026, 3, 3, 18, 0)


def test_none_budget_param_disables_the_budget_check_entirely() -> None:
    """`daily_time_budget_minutes=None` is the Pass-2 physical-only probe mode."""
    effective_hours = every_day("18:00", "21:00")
    budget = no_budget()
    budget["monday"] = 10  # would exclude Monday if the budget mechanism were active

    with_budget = find_first_free_slot(
        duration_minutes=60,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=effective_hours,
        excluded_dates=[],
        daily_time_budget_minutes=budget,
        obstacles=[],
    )
    without_budget = find_first_free_slot(
        duration_minutes=60,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=effective_hours,
        excluded_dates=[],
        daily_time_budget_minutes=None,
        obstacles=[],
    )

    assert with_budget == ny(2026, 3, 3, 18, 0)
    assert without_budget == ny(2026, 3, 2, 18, 0)


def test_no_window_on_any_day_in_range_returns_none() -> None:
    all_excluded = dict.fromkeys(DAY_NAMES, None)

    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=all_excluded,
        excluded_dates=[],
        daily_time_budget_minutes=no_budget(),
        obstacles=[],
    )

    assert slot is None


def test_deadline_mid_window_cuts_off_an_otherwise_fitting_slot() -> None:
    effective_hours = every_day("18:00", "21:00")

    slot = find_first_free_slot(
        duration_minutes=60,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 2, 18, 30),  # deadline instant: only 30 minutes available before it
        allowed_hours=effective_hours,
        excluded_dates=[],
        daily_time_budget_minutes=no_budget(),
        obstacles=[],
    )

    assert slot is None


def test_obstacles_outside_the_window_do_not_block_placement() -> None:
    effective_hours = every_day("18:00", "21:00")
    obstacles = [Obstacle(start=ny(2026, 3, 2, 6, 0), end=ny(2026, 3, 2, 7, 0))]

    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=effective_hours,
        excluded_dates=[],
        daily_time_budget_minutes=no_budget(),
        obstacles=obstacles,
    )

    assert slot == ny(2026, 3, 2, 18, 0)


def test_zero_remaining_budget_day_is_skipped() -> None:
    # The existing obstacle already consumes the entire 60-minute budget - even a
    # 15-minute task must skip this day, not just be denied the obstacle's span.
    budget = {"monday": 60}
    obstacles = [Obstacle(start=ny(2026, 3, 2, 18, 0), end=ny(2026, 3, 2, 19, 0))]

    slot = find_first_free_slot(
        duration_minutes=15,
        not_before=ny(2026, 3, 2, 0, 0),
        not_after=ny(2026, 3, 2, 21, 0),
        allowed_hours={"monday": window("18:00", "21:00")},
        excluded_dates=[],
        daily_time_budget_minutes=budget,
        obstacles=obstacles,
    )

    assert slot is None


def test_empty_obstacle_list_places_at_window_open() -> None:
    effective_hours = every_day("18:00", "21:00")

    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=effective_hours,
        excluded_dates=[],
        daily_time_budget_minutes=no_budget(),
        obstacles=[],
    )

    assert slot == ny(2026, 3, 2, 18, 0)


def test_task_fits_comfortably_within_an_explicit_budget() -> None:
    # An explicit (non-null) per-day budget that the task doesn't come close to
    # exceeding must not block Pass 1 - only a genuine overage should.
    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=every_day("18:00", "21:00"),
        excluded_dates=[],
        daily_time_budget_minutes={"monday": 120},
        obstacles=[],
    )

    assert slot == ny(2026, 3, 2, 18, 0)


def test_fully_contained_obstacle_is_a_no_op() -> None:
    # A larger obstacle fully swallows a smaller one; the smaller must not
    # incorrectly push the cursor backwards or otherwise change the result.
    obstacles = [
        Obstacle(start=ny(2026, 3, 2, 18, 0), end=ny(2026, 3, 2, 20, 0)),
        Obstacle(start=ny(2026, 3, 2, 18, 30), end=ny(2026, 3, 2, 19, 0)),  # fully inside the first
    ]

    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 9, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=every_day("18:00", "21:00"),
        excluded_dates=[],
        daily_time_budget_minutes=no_budget(),
        obstacles=obstacles,
    )

    assert slot == ny(2026, 3, 2, 20, 0)


def test_disjoint_same_day_obstacles_are_both_counted_toward_budget() -> None:
    # Two separate, non-overlapping obstacles on the same day (30 + 30 = 60
    # minutes) must both count toward that day's budget, not just the larger one.
    obstacles = [
        Obstacle(start=ny(2026, 3, 2, 9, 0), end=ny(2026, 3, 2, 9, 30)),
        Obstacle(start=ny(2026, 3, 2, 12, 0), end=ny(2026, 3, 2, 12, 30)),
    ]

    slot = find_first_free_slot(
        duration_minutes=15,
        not_before=ny(2026, 3, 2, 0, 0),
        not_after=ny(2026, 3, 7, 9, 0),
        allowed_hours=every_day("18:00", "21:00"),
        excluded_dates=[],
        daily_time_budget_minutes={"monday": 60},  # exactly the combined obstacle total - zero room left
        obstacles=obstacles,
    )

    assert slot == ny(2026, 3, 3, 18, 0)  # Monday's budget is exhausted -> Tuesday


def test_overlapping_obstacles_are_not_double_counted_toward_budget() -> None:
    # 18:00-19:30 and 19:00-20:00 overlap - 120 real minutes (18:00-20:00), not
    # 150 (90+60) if summed naively. Budget=150 only fits if merged correctly.
    obstacles = [
        Obstacle(start=ny(2026, 3, 2, 18, 0), end=ny(2026, 3, 2, 19, 30)),
        Obstacle(start=ny(2026, 3, 2, 19, 0), end=ny(2026, 3, 2, 20, 0)),
    ]

    slot = find_first_free_slot(
        duration_minutes=30,
        not_before=ny(2026, 3, 2, 0, 0),
        not_after=ny(2026, 3, 2, 21, 0),
        allowed_hours={"monday": window("18:00", "21:00")},
        excluded_dates=[],
        daily_time_budget_minutes={"monday": 150},
        obstacles=obstacles,
    )

    assert slot == ny(2026, 3, 2, 20, 0)
