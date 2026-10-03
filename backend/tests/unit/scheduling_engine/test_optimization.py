"""The plan behind "Optimize Schedule" (design doc §6.11, Rev 14): Worked Examples S-U as
fixtures, every outcome kind, the degradation rule and the "fewer placed" guard.

Every evening has a 18:00-20:00 window; Mon 2026-04-06 12:00 is "now" (no DST change in the week).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.scheduling_engine.optimization import CurrentSlot, OptimizationPlan, plan_optimization
from app.scheduling_engine.placement import schedule_pending_flexible_tasks
from app.scheduling_engine.types import FlexibleTaskCandidate, Obstacle
from tests.fixtures.scheduling import every_day, no_budget, ny

NOW = ny(2026, 4, 6, 12)
HOURS = every_day("18:00", "20:00")
LOW, MEDIUM, HIGH = 1, 2, 3


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return ny(2026, 4, day, hour, minute)


def task(task_id: str, minutes: int, deadline: datetime, priority: int) -> FlexibleTaskCandidate:
    return FlexibleTaskCandidate(id=task_id, deadline=deadline, priority=priority, estimated_duration_minutes=minutes)


def arrive_one_at_a_time(
    tasks: list[FlexibleTaskCandidate], order: list[str], *, budget: dict[str, int | None] | None = None
) -> dict[str, CurrentSlot]:
    """Today's schedule, built the way §6.2 builds it: each task placed alone, in arrival order."""
    by_id = {t.id: t for t in tasks}
    placed: dict[str, CurrentSlot] = {}
    obstacles: list[Obstacle] = []
    for task_id in order:
        result = schedule_pending_flexible_tasks(
            [by_id[task_id]],
            now=NOW,
            active_hours=HOURS,
            blackout_dates=[],
            daily_time_budget_minutes=budget or no_budget(),
            budget_enforcement="soft",
            obstacles=obstacles,
        )
        for placement in result.placements:
            placed[task_id] = CurrentSlot(placement.scheduled_start, by_id[task_id].estimated_duration_minutes)
            obstacles.append(
                Obstacle(
                    start=placement.scheduled_start,
                    end=placement.scheduled_start + timedelta(minutes=by_id[task_id].estimated_duration_minutes),
                )
            )
    return placed


def plan(
    tasks: list[FlexibleTaskCandidate],
    current: dict[str, CurrentSlot],
    *,
    budget: dict[str, int | None] | None = None,
    enforcement: str = "soft",
    obstacles: list[Obstacle] | None = None,
) -> OptimizationPlan:
    return plan_optimization(
        tasks,
        current,
        now=NOW,
        active_hours=HOURS,
        blackout_dates=[],
        daily_time_budget_minutes=budget or no_budget(),
        budget_enforcement=enforcement,  # type: ignore[arg-type]
        obstacles=obstacles or [],
    )


def starts(plan_: OptimizationPlan) -> dict[str, tuple[str, datetime]]:
    return {
        **{m.task_id: ("moved", m.to_start) for m in plan_.moved},
        **{p.task_id: ("new", p.to_start) for p in plan_.newly_scheduled},
    }


class TestWorkedExamples:
    def test_example_s_a_clean_gain_applies_at_once(self) -> None:
        tasks = [task("B", 30, at(8, 20), HIGH), task("C", 60, at(7, 20), LOW), task("A", 60, at(6, 20), LOW)]
        current = arrive_one_at_a_time(tasks, ["B", "C", "A"])
        assert {k: v.start for k, v in current.items()} == {"B": at(6, 18), "C": at(6, 18, 30)}

        result = plan(tasks, current)

        assert starts(result) == {"A": ("new", at(6, 18)), "B": ("moved", at(7, 18)), "C": ("moved", at(6, 19))}
        assert result.lost == () and result.over_budget_ids == ()
        assert result.classify() == ("applied", None)

    def test_example_t_a_swap_that_loses_a_task_needs_approval(self) -> None:
        tasks = [task("B", 60, at(6, 20), HIGH), task("A", 60, at(6, 20), LOW), task("C", 60, at(6, 20), MEDIUM)]
        current = arrive_one_at_a_time(tasks, ["B", "A", "C"])
        assert {k: v.start for k, v in current.items()} == {"B": at(6, 18), "A": at(6, 19)}

        result = plan(tasks, current)

        assert [loss.task_id for loss in result.lost] == ["A"]
        assert starts(result) == {"C": ("new", at(6, 19))}
        assert result.unchanged == ("B",)
        assert (result.placed_before, result.placed_after) == (2, 2)  # the same number, but A was had
        assert result.classify() == ("needs_approval", None)

    def test_example_u_a_plan_placing_fewer_tasks_is_not_offered(self) -> None:
        tasks = [task("B", 60, at(6, 20), MEDIUM), task("C", 60, at(6, 20), LOW), task("A", 90, at(6, 20), HIGH)]
        current = arrive_one_at_a_time(tasks, ["B", "C", "A"])
        assert set(current) == {"B", "C"}

        result = plan(tasks, current)

        assert (result.placed_before, result.placed_after) == (2, 1)
        assert result.classify() == ("nothing_to_do", "would_place_fewer")


class TestOutcomeKinds:
    def test_an_already_best_schedule_is_identical_and_there_is_nothing_to_do(self) -> None:
        tasks = [task("A", 60, at(6, 20), HIGH)]
        current = arrive_one_at_a_time(tasks, ["A"])
        result = plan(tasks, current)
        assert result.unchanged == ("A",) and not result.changes_anything
        assert result.classify() == ("nothing_to_do", "identical")

    def test_a_task_nothing_can_place_is_still_unplaced_and_not_a_change(self) -> None:
        tasks = [task("A", 60, at(6, 20), HIGH), task("Z", 60, at(6, 12, 30), LOW)]  # Z's deadline is before any window
        current = arrive_one_at_a_time(tasks, ["A", "Z"])
        result = plan(tasks, current)
        assert result.still_unplaced == ("Z",)
        assert result.classify() == ("nothing_to_do", "identical")

    def test_changes_are_listed_in_chronological_order_of_their_new_time(self) -> None:
        tasks = [task("L", 60, at(9, 20), LOW), task("M", 60, at(7, 20), LOW), task("N", 60, at(6, 20), LOW)]
        current = arrive_one_at_a_time(tasks, ["L", "M", "N"])
        result = plan(tasks, current)
        times = [m.to_start for m in result.moved] + [p.to_start for p in result.newly_scheduled]
        assert [m.to_start for m in result.moved] == sorted(m.to_start for m in result.moved)
        assert times  # something changed

    def test_obstacles_that_stay_put_are_respected(self) -> None:
        tasks = [task("A", 60, at(6, 20), LOW)]
        fixed = [Obstacle(start=at(6, 18), end=at(6, 19))]
        result = plan(tasks, {}, obstacles=fixed)
        assert starts(result) == {"A": ("new", at(6, 19))}

    def test_the_signature_changes_when_anything_the_user_would_see_changes(self) -> None:
        tasks = [task("A", 60, at(6, 20), LOW), task("B", 60, at(6, 20), HIGH)]
        first = plan(tasks, {})
        again = plan(tasks, {})
        other = plan(tasks, {}, obstacles=[Obstacle(start=at(6, 18), end=at(6, 18, 30))])
        assert first.signature() == again.signature()
        assert first.signature() != other.signature()


class TestBudgets:
    def test_a_task_newly_pushed_onto_a_day_over_its_budget_is_a_degradation(self) -> None:
        budget = {**no_budget(), "monday": 60, "tuesday": 60}
        tasks = [task("X", 60, at(6, 20), HIGH), task("Y", 60, at(7, 20), LOW), task("Z", 60, at(7, 20), LOW)]
        current = arrive_one_at_a_time(tasks, ["Y", "Z", "X"], budget=budget)
        # Today X squeezed onto Monday beside Y (over Monday's budget), Z is alone on Tuesday.
        assert {k: v.start for k, v in current.items()} == {"Y": at(6, 18), "Z": at(7, 18), "X": at(6, 19)}

        result = plan(tasks, current, budget=budget)

        # Globally X takes Monday alone (no longer over), Y moves to Tuesday and Z shares it: Z is newly over.
        assert result.over_budget_ids == ("Z",)
        assert result.lost == ()
        assert result.has_degradation
        assert result.classify() == ("needs_approval", None)

    def test_tasks_already_over_budget_today_are_not_newly_over_budget(self) -> None:
        budget = {**no_budget(), "monday": 60}
        tasks = [task("A", 60, at(6, 20), LOW), task("B", 60, at(6, 20), HIGH)]
        current = {"A": CurrentSlot(at(6, 18), 60), "B": CurrentSlot(at(6, 19), 60)}  # 120 minutes on a 60 budget
        result = plan(tasks, current, budget=budget)
        assert result.over_budget_ids == ()
        # Moving A to Tuesday gets everyone within budget: a clean improvement, no approval.
        assert result.classify() == ("applied", None)

    def test_a_strict_budget_never_produces_an_over_budget_placement(self) -> None:
        budget = {**no_budget(), "monday": 60}
        tasks = [task("A", 60, at(6, 20), LOW), task("B", 60, at(6, 20), HIGH)]
        result = plan(tasks, {}, budget=budget, enforcement="strict")
        assert result.over_budget_ids == ()
        assert len(result.newly_scheduled) == 1

    def test_a_task_that_keeps_its_slot_but_whose_day_goes_over_budget_is_flagged(self) -> None:
        budget = {**no_budget(), "monday": 60}
        # Y keeps Monday 18:00. W, with a Monday deadline, can only be placed beside it - over budget.
        tasks = [task("Y", 60, at(6, 20), HIGH), task("W", 60, at(6, 20), LOW)]
        result = plan(tasks, {"Y": CurrentSlot(at(6, 18), 60)}, budget=budget)

        assert result.unchanged == ("Y",)
        assert result.newly_over_budget_unchanged == ("Y",)
        assert [p.task_id for p in result.newly_scheduled if p.newly_over_budget] == ["W"]
        assert set(result.over_budget_ids) == {"Y", "W"}
        assert result.classify() == ("needs_approval", None)
