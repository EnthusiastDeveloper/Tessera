"""Unit tests for app.scheduling_engine.placement.schedule_pending_flexible_tasks (§6.2 full algorithm).

Examples E, G, H, J, and N's step-2 placement arithmetic are transcribed directly
from design doc §10.
"""

from app.scheduling_engine.placement import schedule_pending_flexible_tasks
from app.scheduling_engine.types import BlackoutDate, FlexibleTaskCandidate, Obstacle, Placement, SchedulingResult
from tests.fixtures.scheduling import every_day, no_budget, ny, ny_date, window


def test_example_e_unschedulable_but_feasible() -> None:
    """Contrast with §6.8's Example I: placeable in principle, merely unlucky - accepted then reported, not rejected."""
    active_hours = every_day("18:00", "21:00")
    obstacles = [
        Obstacle(ny(2026, 3, 2, 18, 0), ny(2026, 3, 2, 20, 0)),
        Obstacle(ny(2026, 3, 3, 18, 0), ny(2026, 3, 3, 20, 0)),
        Obstacle(ny(2026, 3, 4, 18, 0), ny(2026, 3, 4, 20, 0)),
    ]
    candidate = FlexibleTaskCandidate(
        id="annual-review", deadline=ny(2026, 3, 5, 9, 0), priority=2, estimated_duration_minutes=150
    )

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 2, 9, 0),
        active_hours=active_hours,
        blackout_dates=[],
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=obstacles,
    )

    assert result.placements == ()
    assert result.unschedulable_task_ids == ("annual-review",)


def test_example_g_daily_budget_yields_to_deadline() -> None:
    obstacles = [Obstacle(ny(2026, 3, 7, 9, 0), ny(2026, 3, 7, 11, 30))]  # 150 minutes of existing chores
    candidate = FlexibleTaskCandidate(id="garage", deadline=ny(2026, 3, 7, 21, 0), priority=2, estimated_duration_minutes=90)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 7, 0, 0),
        active_hours={"saturday": window("09:00", "21:00")},
        blackout_dates=[],
        daily_time_budget_minutes={"saturday": 180},
        budget_enforcement="soft",
        obstacles=obstacles,
    )

    # Pass 1 fails (150+90=240 > 180); Pass 2 finds Saturday physically free from 11:30.
    assert result.placements == (Placement("garage", ny(2026, 3, 7, 11, 30), True),)
    assert result.unschedulable_task_ids == ()


def test_example_h_pass_two_picks_least_damaging_day_not_earliest() -> None:
    # Sunday 2026-03-01, Monday 03-02, Tuesday 03-03, Wednesday 03-04.
    active_hours = {
        "sunday": window("19:00", "21:00"),
        "monday": window("19:00", "21:00"),
        "tuesday": window("19:00", "21:00"),
        "wednesday": window("19:00", "21:00"),
    }
    obstacles = [
        Obstacle(ny(2026, 3, 3, 19, 0), ny(2026, 3, 3, 21, 0)),  # Tuesday fully booked
        Obstacle(ny(2026, 3, 4, 19, 0), ny(2026, 3, 4, 21, 0)),  # Wednesday fully booked
    ]
    candidate = FlexibleTaskCandidate(id="chore", deadline=ny(2026, 3, 5, 21, 0), priority=2, estimated_duration_minutes=20)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 1, 0, 0),
        active_hours=active_hours,
        blackout_dates=[],
        daily_time_budget_minutes={"sunday": 10, "monday": 17},
        budget_enforcement="soft",
        obstacles=obstacles,
    )

    # Sunday overage = 20-10 = 10; Monday overage = 20-17 = 3. Monday wins despite
    # coming second chronologically among the two physically-free days.
    assert result.placements == (Placement("chore", ny(2026, 3, 2, 19, 0), True),)


def test_example_j_pass_two_slack_tie_break() -> None:
    obstacles = [
        Obstacle(ny(2026, 3, 3, 18, 0), ny(2026, 3, 3, 20, 0)),  # Tuesday: 120 committed minutes
        Obstacle(ny(2026, 3, 4, 15, 0), ny(2026, 3, 4, 16, 0)),  # Wednesday: 60 committed minutes
    ]
    candidate = FlexibleTaskCandidate(id="j-task", deadline=ny(2026, 3, 4, 21, 0), priority=2, estimated_duration_minutes=60)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 3, 0, 0),
        active_hours={
            "tuesday": window("18:00", "21:00"),  # 180-minute window
            "wednesday": window("15:00", "21:00"),  # 360-minute window
        },
        blackout_dates=[],
        daily_time_budget_minutes={"tuesday": 120, "wednesday": 60},
        budget_enforcement="soft",
        obstacles=obstacles,
    )

    # Both days tie at exactly 60 minutes of overage; Wednesday leaves 240 minutes
    # of slack afterward vs. Tuesday's 0 (wall-to-wall), so Wednesday wins.
    assert result.placements == (Placement("j-task", ny(2026, 3, 4, 16, 0), True),)


def test_example_n_step_two_dependency_earliest_start_and_grid() -> None:
    """Task 2 unblocks when Task 1 completes; placed at the first grid point at/after that instant."""
    candidate = FlexibleTaskCandidate(
        id="inspection",
        deadline=ny(2026, 3, 10, 21, 0),
        priority=2,
        estimated_duration_minutes=90,
        dependency_completed_at=[ny(2026, 3, 4, 19, 30)],
    )

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 1, 0, 0),
        active_hours=every_day("18:00", "21:00"),
        blackout_dates=[],
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=[],
    )

    # 19:30 is already grid-aligned, and 19:30 + 90min = 21:00 exactly fills the window.
    assert result.placements == (Placement("inspection", ny(2026, 3, 4, 19, 30), False),)


def test_candidate_with_no_dependencies_uses_now_as_earliest_start() -> None:
    candidate = FlexibleTaskCandidate(id="no-deps", deadline=ny(2026, 3, 7, 9, 0), priority=2, estimated_duration_minutes=30)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 2, 9, 0),
        active_hours=every_day("18:00", "21:00"),
        blackout_dates=[],
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=[],
    )

    assert result.placements == (Placement("no-deps", ny(2026, 3, 2, 18, 0), False),)


def test_strict_budget_enforcement_never_runs_pass_two() -> None:
    # Saturday is physically wide open (no obstacles) - only the budget blocks it.
    # Under "strict", that must be enough to make the task unschedulable outright.
    candidate = FlexibleTaskCandidate(id="strict-task", deadline=ny(2026, 3, 7, 21, 0), priority=2, estimated_duration_minutes=30)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 7, 0, 0),
        active_hours={"saturday": window("18:00", "21:00")},
        blackout_dates=[],
        daily_time_budget_minutes={"saturday": 10},
        budget_enforcement="strict",
        obstacles=[],
    )

    assert result.placements == ()
    assert result.unschedulable_task_ids == ("strict-task",)


def test_deadline_equal_to_now_is_unschedulable() -> None:
    moment = ny(2026, 3, 2, 12, 0)
    candidate = FlexibleTaskCandidate(id="too-late", deadline=moment, priority=2, estimated_duration_minutes=15)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=moment,
        active_hours=every_day("00:00", "23:45"),
        blackout_dates=[],
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=[],
    )

    assert result.placements == ()
    assert result.unschedulable_task_ids == ("too-late",)


def test_empty_candidate_list_returns_empty_result() -> None:
    result = schedule_pending_flexible_tasks(
        candidates=[],
        now=ny(2026, 3, 2, 9, 0),
        active_hours=every_day("18:00", "21:00"),
        blackout_dates=[],
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=[],
    )

    assert result == SchedulingResult(placements=(), unschedulable_task_ids=())


def test_pass_two_three_way_tie_break_prefers_earliest_date() -> None:
    # Monday and Tuesday are configured identically, so overage and remaining
    # slack tie exactly - only the calendar date differs, and it must decide.
    active_hours = {"monday": window("18:00", "19:00"), "tuesday": window("18:00", "19:00")}
    candidate = FlexibleTaskCandidate(id="tie", deadline=ny(2026, 3, 3, 21, 0), priority=2, estimated_duration_minutes=20)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 2, 0, 0),
        active_hours=active_hours,
        blackout_dates=[],
        daily_time_budget_minutes={"monday": 10, "tuesday": 10},
        budget_enforcement="soft",
        obstacles=[],
    )

    assert result.placements == (Placement("tie", ny(2026, 3, 2, 18, 0), True),)


def test_earlier_deadline_is_processed_before_higher_priority() -> None:
    """Sort is (deadline ASC, priority DESC) - deadline is primary, priority only breaks ties."""
    # Only Monday has a window, and it fits exactly one 30-minute task. Both
    # candidates' only chance is that single Monday slot. If sort order were
    # priority-first instead of deadline-first, "later" (priority 4) would claim
    # it and "urgent" (deadline Monday, priority 1) would wrongly go unscheduled.
    active_hours = {"monday": window("18:00", "18:30")}
    urgent_low_priority = FlexibleTaskCandidate(
        id="urgent", deadline=ny(2026, 3, 2, 21, 0), priority=1, estimated_duration_minutes=30
    )
    later_deadline_critical = FlexibleTaskCandidate(
        id="later", deadline=ny(2026, 3, 6, 21, 0), priority=4, estimated_duration_minutes=30
    )

    result = schedule_pending_flexible_tasks(
        candidates=[later_deadline_critical, urgent_low_priority],  # given out of order deliberately
        now=ny(2026, 3, 2, 0, 0),
        active_hours=active_hours,
        blackout_dates=[],
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=[],
    )

    assert [p.task_id for p in result.placements] == ["urgent"]
    assert result.unschedulable_task_ids == ("later",)


def test_same_deadline_ties_break_by_priority_descending() -> None:
    active_hours = every_day("18:00", "19:00")  # exactly 60 minutes: room for two 30-minute tasks
    low_priority = FlexibleTaskCandidate(id="low", deadline=ny(2026, 3, 2, 21, 0), priority=1, estimated_duration_minutes=30)
    high_priority = FlexibleTaskCandidate(id="high", deadline=ny(2026, 3, 2, 21, 0), priority=4, estimated_duration_minutes=30)

    result = schedule_pending_flexible_tasks(
        candidates=[low_priority, high_priority],  # given out of order deliberately
        now=ny(2026, 3, 2, 0, 0),
        active_hours=active_hours,
        blackout_dates=[],
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=[],
    )

    by_id = {placement.task_id: placement.scheduled_start for placement in result.placements}
    assert by_id["high"] == ny(2026, 3, 2, 18, 0)
    assert by_id["low"] == ny(2026, 3, 2, 18, 30)


def test_pass_two_skips_a_blacked_out_day() -> None:
    # Monday is blacked out and Tuesday's budget is too small for Pass 1 to
    # succeed on either day - forcing Pass 2, which must still respect the
    # blackout rather than treating Monday as fair game once budget is ignored.
    candidate = FlexibleTaskCandidate(id="task", deadline=ny(2026, 3, 3, 21, 0), priority=2, estimated_duration_minutes=60)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 2, 0, 0),
        active_hours={"monday": window("18:00", "19:00"), "tuesday": window("18:00", "19:00")},
        blackout_dates=[BlackoutDate(start=ny_date(2026, 3, 2), end=ny_date(2026, 3, 2))],
        daily_time_budget_minutes={"monday": 10, "tuesday": 10},
        budget_enforcement="soft",
        obstacles=[],
    )

    assert result.placements == (Placement("task", ny(2026, 3, 3, 18, 0), True),)


def test_intra_pass_placement_becomes_an_obstacle_for_the_next_candidate() -> None:
    """A task placed earlier in the same pass must block a same-deadline, lower-priority task from double-booking it."""
    active_hours = {"monday": window("18:00", "18:30")}  # room for exactly one 30-minute task
    first = FlexibleTaskCandidate(id="first", deadline=ny(2026, 3, 2, 21, 0), priority=4, estimated_duration_minutes=30)
    second = FlexibleTaskCandidate(id="second", deadline=ny(2026, 3, 2, 21, 0), priority=1, estimated_duration_minutes=30)

    result = schedule_pending_flexible_tasks(
        candidates=[first, second],
        now=ny(2026, 3, 2, 0, 0),
        active_hours=active_hours,
        blackout_dates=[],
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=[],
    )

    assert [p.task_id for p in result.placements] == ["first"]
    assert result.unschedulable_task_ids == ("second",)


def test_pass_two_slack_tie_break_is_dst_correct() -> None:
    """Regression: naive datetime subtraction silently ignores DST, corrupting the slack tie-break.

    2026-03-08 is the US DST spring-forward day (2:00am -> 3:00am is skipped).
    Sunday's window (01:00-04:00) is only 120 real minutes, not the 180 a naive
    wall-clock subtraction would report; Monday's window (01:00-03:30, no DST
    involved) is a plain 150. With duration=100 and a too-small budget forcing
    Pass 2 on both days, correct DST-aware slack makes Monday's true 50 minutes
    remaining beat Sunday's true 20 - a naive computation would instead see
    Sunday's (wrong) 80 minutes remaining and pick Sunday.
    """
    candidate = FlexibleTaskCandidate(id="task", deadline=ny(2026, 3, 9, 21, 0), priority=2, estimated_duration_minutes=100)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 8, 0, 0),
        active_hours={"sunday": window("01:00", "04:00"), "monday": window("01:00", "03:30")},
        blackout_dates=[],
        daily_time_budget_minutes={"sunday": 50, "monday": 50},
        budget_enforcement="soft",
        obstacles=[],
    )

    assert result.placements == (Placement("task", ny(2026, 3, 9, 1, 0), True),)


def test_committed_minutes_are_dst_correct_across_a_spring_forward_obstacle() -> None:
    """Regression: same DST pitfall, this time in the budget/committed-minutes accounting.

    An obstacle spanning 01:00-04:00 on 2026-03-08 (the spring-forward day) is
    only 120 real minutes, not 180. With a 130-minute budget and a 10-minute
    task, the correct 120+10=130 fits within Pass 1 directly; a naive 180+10=190
    would wrongly reject Pass 1 and fall through to a Pass 2 override instead -
    same slot, wrong `budget_overridden` flag.
    """
    obstacles = [Obstacle(ny(2026, 3, 8, 1, 0), ny(2026, 3, 8, 4, 0))]
    candidate = FlexibleTaskCandidate(id="task", deadline=ny(2026, 3, 8, 21, 0), priority=2, estimated_duration_minutes=10)

    result = schedule_pending_flexible_tasks(
        candidates=[candidate],
        now=ny(2026, 3, 8, 0, 0),
        active_hours={"sunday": window("01:00", "05:00")},
        blackout_dates=[],
        daily_time_budget_minutes={"sunday": 130},
        budget_enforcement="soft",
        obstacles=obstacles,
    )

    assert result.placements == (Placement("task", ny(2026, 3, 8, 4, 0), False),)
