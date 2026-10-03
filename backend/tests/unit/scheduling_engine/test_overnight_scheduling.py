"""The scheduling algorithm against overnight windows, merged stretches and midnight-crossing
slots (design doc §3.7, §6.2, §6.8; Rev 13) - the scenarios `test_window_lists.py` does not
already pin down: the full multi-task algorithm, boundary arithmetic, how overrides and
blackouts treat a window's spill-over, budgets that straddle midnight, and a brute-force
oracle the engine is compared against on many generated weeks.

Weeks used are free of daylight-saving changes (DST has its own tests in `test_window_lists.py`):
Mon 2026-04-06 .. Sun 2026-04-12, America/New_York. The oracle works in UTC, where every
day has 24 hours, so its minute arithmetic is trivially right.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.scheduling_engine.calendar_rules import day_name, eligible_intervals, validate_day_windows
from app.scheduling_engine.feasibility import validate_feasible_duration
from app.scheduling_engine.placement import (
    committed_minutes_for_day,
    find_first_free_slot,
    schedule_pending_flexible_tasks,
)
from app.scheduling_engine.types import (
    DAY_NAMES,
    ActiveHoursMap,
    ActiveHoursWindow,
    BlackoutDate,
    FlexibleTaskCandidate,
    Obstacle,
)
from tests.fixtures.scheduling import NY, no_budget, ny, ny_date, window

MON, TUE, WED = (ny(2026, 4, 6), ny(2026, 4, 7), ny(2026, 4, 8))


def at(day: int, hour: int = 0, minute: int = 0) -> datetime:
    """April `day` 2026, New York - Mon 6th .. Sun 12th, then Mon 13th, and on past the end of the month."""
    return ny(2026, 4, 1, hour, minute) + timedelta(days=day - 1)


def only(**days: list[ActiveHoursWindow]) -> dict[str, list[ActiveHoursWindow] | None]:
    """An active-hours map where every day not named is excluded."""
    return {day: days.get(day) for day in DAY_NAMES}


NIGHT = only(monday=[window("22:00", "02:00")])  # Mon 22:00 -> Tue 02:00, four hours


def first_slot(duration: int, hours: ActiveHoursMap, *, start: datetime, end: datetime, **kwargs: object) -> datetime | None:
    arguments: dict[str, object] = {
        "duration_minutes": duration,
        "not_before": start,
        "not_after": end,
        "allowed_hours": hours,
        "excluded_dates": [],
        "daily_time_budget_minutes": no_budget(),
        "obstacles": [],
    }
    arguments.update(kwargs)
    return find_first_free_slot(**arguments)  # type: ignore[arg-type]


def candidate(task_id: str, minutes: int, deadline: datetime, priority: int = 2, **kwargs: object) -> FlexibleTaskCandidate:
    return FlexibleTaskCandidate(
        id=task_id,
        deadline=deadline,
        priority=priority,
        estimated_duration_minutes=minutes,
        **kwargs,  # type: ignore[arg-type]
    )


def run(candidates: list[FlexibleTaskCandidate], hours: ActiveHoursMap, *, now: datetime, **kwargs: object):  # type: ignore[no-untyped-def]
    arguments: dict[str, object] = {
        "now": now,
        "active_hours": hours,
        "blackout_dates": [],
        "daily_time_budget_minutes": no_budget(),
        "budget_enforcement": "soft",
        "obstacles": [],
    }
    arguments.update(kwargs)
    return schedule_pending_flexible_tasks(candidates, **arguments)  # type: ignore[arg-type]


def starts(result) -> dict[str, datetime]:  # type: ignore[no-untyped-def]
    return {placement.task_id: placement.scheduled_start for placement in result.placements}


class TestSeveralTasksShareAStretch:
    def test_four_one_hour_tasks_exactly_fill_the_night_and_a_fifth_has_no_room(self) -> None:
        tasks = [candidate(f"t{i}", 60, at(7, 12)) for i in range(5)]
        result = run(tasks, NIGHT, now=at(6, 12))
        assert [starts(result)[f"t{i}"] for i in range(4)] == [at(6, 22), at(6, 23), at(7, 0), at(7, 1)]
        assert result.unschedulable_task_ids == ("t4",)

    def test_a_third_ninety_minute_task_does_not_fit_the_remaining_half_hour(self) -> None:
        tasks = [candidate(f"t{i}", 90, at(7, 12)) for i in range(3)]
        result = run(tasks, NIGHT, now=at(6, 12))
        assert starts(result) == {"t0": at(6, 22), "t1": at(6, 23, 30)}  # 01:00-02:30 would overrun 02:00
        assert result.unschedulable_task_ids == ("t2",)

    def test_the_overflow_task_takes_the_next_weeks_night_when_its_deadline_allows(self) -> None:
        tasks = [candidate("a", 150, at(14, 12)), candidate("b", 150, at(14, 12))]
        result = run(tasks, NIGHT, now=at(6, 12))
        assert starts(result) == {"a": at(6, 22), "b": at(13, 22)}

    def test_an_earlier_deadline_inside_the_stretch_is_served_first(self) -> None:
        tight = candidate("tight", 90, at(7, 0, 30))  # must finish by 00:30
        loose = candidate("loose", 90, at(7, 12))
        result = run([loose, tight], NIGHT, now=at(6, 12))
        assert starts(result) == {"tight": at(6, 22), "loose": at(6, 23, 30)}


class TestEdgesOfAStretch:
    def test_a_task_that_ends_exactly_at_the_stretch_end_fits(self) -> None:
        assert first_slot(240, NIGHT, start=at(6, 12), end=at(8, 0)) == at(6, 22)
        assert first_slot(241, NIGHT, start=at(6, 12), end=at(8, 0)) is None

    def test_a_deadline_exactly_at_the_stretch_end_allows_it_and_a_minute_earlier_does_not(self) -> None:
        assert first_slot(240, NIGHT, start=at(6, 12), end=at(7, 2)) == at(6, 22)
        assert first_slot(240, NIGHT, start=at(6, 12), end=at(7, 1, 59)) is None

    def test_now_after_midnight_inside_the_stretch_places_on_the_next_grid_point(self) -> None:
        result = run([candidate("t", 60, at(9, 12))], NIGHT, now=at(7, 0, 20))
        assert starts(result) == {"t": at(7, 0, 30)}  # Monday's window, Tuesday's clock

    def test_now_exactly_at_the_stretch_end_waits_for_next_weeks_stretch(self) -> None:
        result = run([candidate("t", 60, at(15, 12))], NIGHT, now=at(7, 2, 0))
        assert starts(result) == {"t": at(13, 22)}

    def test_a_window_that_ends_at_midnight_is_an_overnight_window_of_exactly_that_length(self) -> None:
        hours = only(monday=[window("22:00", "00:00")])
        (stretch,) = eligible_intervals(ny_date(2026, 4, 6), ny_date(2026, 4, 7), hours, [], NY)
        assert stretch == (at(6, 22), at(7, 0))
        assert first_slot(120, hours, start=at(6, 12), end=at(8, 0)) == at(6, 22)
        assert first_slot(121, hours, start=at(6, 12), end=at(8, 0)) is None

    def test_a_blackout_on_the_next_date_does_not_touch_a_window_that_ends_at_midnight(self) -> None:
        hours = only(monday=[window("22:00", "00:00")])
        tuesday_off = [BlackoutDate(start=ny_date(2026, 4, 7), end=ny_date(2026, 4, 7))]
        assert first_slot(120, hours, start=at(6, 12), end=at(8, 0), excluded_dates=tuesday_off) == at(6, 22)

    def test_a_nearly_round_the_clock_overnight_window_is_one_stretch_of_23_hours_59(self) -> None:
        hours = only(monday=[window("06:00", "05:59")])
        (stretch,) = eligible_intervals(ny_date(2026, 4, 6), ny_date(2026, 4, 7), hours, [], NY)
        assert stretch == (at(6, 6), at(7, 5, 59))
        assert validate_feasible_duration(1439, hours) is True
        assert validate_feasible_duration(1440, hours) is False
        assert first_slot(1425, hours, start=at(6, 0), end=at(8, 0)) == at(6, 6)

    def test_a_start_that_is_not_on_the_grid_shifts_the_slots_and_an_unaligned_end_clips_them(self) -> None:
        hours = only(monday=[window("22:07", "01:50")])
        result = run([candidate(f"t{i}", 60, at(7, 12)) for i in range(4)], hours, now=at(6, 12))
        # 22:15, 23:15, 00:15 - and 01:15 would end at 02:15, past 01:50.
        assert [starts(result)[f"t{i}"] for i in range(3)] == [at(6, 22, 15), at(6, 23, 15), at(7, 0, 15)]
        assert result.unschedulable_task_ids == ("t3",)


class TestObstaclesAcrossMidnight:
    def test_an_event_straddling_midnight_leaves_only_the_time_before_it(self) -> None:
        event = [Obstacle(start=at(6, 23), end=at(7, 1))]
        assert first_slot(60, NIGHT, start=at(6, 12), end=at(7, 12), obstacles=event) == at(6, 22)
        # 90 minutes does not fit before 23:00, and after 01:00 only an hour remains.
        assert first_slot(90, NIGHT, start=at(6, 12), end=at(7, 12), obstacles=event) is None

    def test_an_event_filling_the_whole_stretch_pushes_the_task_a_week(self) -> None:
        event = [Obstacle(start=at(6, 22), end=at(7, 2))]
        assert first_slot(60, NIGHT, start=at(6, 12), end=at(14, 12), obstacles=event) == at(13, 22)

    def test_a_sparse_horizon_still_finds_the_one_free_night(self) -> None:
        weeks = range(9)
        busy = [Obstacle(start=at(6 + 7 * week, 22), end=at(7 + 7 * week, 2)) for week in weeks]
        slot = first_slot(60, NIGHT, start=at(6, 12), end=at(6 + 7 * 10, 12), obstacles=busy)
        assert slot == at(6 + 7 * 9, 22)  # the ninth Monday, 63 days on

    def test_obstacles_are_not_mutated_and_the_input_order_does_not_matter(self) -> None:
        events = [Obstacle(start=at(7, 0), end=at(7, 1)), Obstacle(start=at(6, 22), end=at(6, 23))]
        snapshot = list(events)
        forward = first_slot(60, NIGHT, start=at(6, 12), end=at(7, 12), obstacles=events)
        backward = first_slot(60, NIGHT, start=at(6, 12), end=at(7, 12), obstacles=list(reversed(events)))
        assert forward == backward == at(6, 23)
        assert events == snapshot


class TestWindowsOfNeighbouringDays:
    def test_windows_that_overlap_across_midnight_merge_into_one_stretch(self) -> None:
        hours = only(monday=[window("22:00", "04:00")], tuesday=[window("02:00", "08:00")])
        (stretch,) = eligible_intervals(ny_date(2026, 4, 6), ny_date(2026, 4, 7), hours, [], NY)
        assert stretch == (at(6, 22), at(7, 8))
        assert first_slot(600, hours, start=at(6, 12), end=at(8, 0)) == at(6, 22)
        assert first_slot(601, hours, start=at(6, 12), end=at(8, 0)) is None

    def test_windows_one_minute_apart_do_not_merge(self) -> None:
        hours = only(monday=[window("22:00", "23:59")], tuesday=[window("00:00", "06:00")])
        assert len(eligible_intervals(ny_date(2026, 4, 6), ny_date(2026, 4, 7), hours, [], NY)) == 2
        assert first_slot(120, hours, start=at(6, 12), end=at(7, 12)) == at(7, 0)  # needs the 6 h one

    def test_a_split_day_with_an_overnight_second_window_gives_a_morning_and_a_night_stretch(self) -> None:
        hours = only(monday=[window("01:00", "03:00"), window("22:00", "02:00")])
        assert eligible_intervals(ny_date(2026, 4, 6), ny_date(2026, 4, 6), hours, [], NY) == [
            (at(6, 1), at(6, 3)),
            (at(6, 22), at(7, 2)),
        ]
        # Tuesday 00:00-02:00 belongs to Monday's night; the Tuesday morning has no window of its own.
        assert first_slot(120, hours, start=at(7, 0), end=at(7, 12)) == at(7, 0)
        assert first_slot(150, hours, start=at(7, 0), end=at(7, 12)) is None

    def test_a_days_own_excluded_marker_does_not_cancel_the_previous_nights_spill(self) -> None:
        hours = {**NIGHT, "tuesday": None}  # Tuesday itself is excluded - Monday's night still reaches into it
        assert first_slot(60, hours, start=at(7, 0), end=at(7, 12)) == at(7, 0)

    def test_a_blackout_on_that_date_does_cancel_it(self) -> None:
        tuesday_off = [BlackoutDate(start=ny_date(2026, 4, 7), end=ny_date(2026, 4, 7))]
        assert first_slot(60, NIGHT, start=at(7, 0), end=at(7, 12), excluded_dates=tuesday_off) is None

    def test_a_multi_day_blackout_removes_every_night_inside_it_and_cuts_the_edges(self) -> None:
        every_night = only(**{day: [window("22:00", "02:00")] for day in DAY_NAMES})
        off = [BlackoutDate(start=ny_date(2026, 4, 7), end=ny_date(2026, 4, 8))]  # Tue and Wed
        stretches = eligible_intervals(ny_date(2026, 4, 6), ny_date(2026, 4, 9), every_night, off, NY)
        assert stretches == [
            (at(5, 22), at(6, 2)),  # Sunday's night, reaching into the range from the day before it
            (at(6, 22), at(7, 0)),  # Monday's night, cut at Tuesday's midnight
            # Tuesday's night and Wednesday's evening are gone entirely; Wednesday's night survives
            # only from Thursday's midnight, since Thursday is not blacked out.
            (at(9, 0), at(9, 2)),
            (at(9, 22), at(10, 2)),
        ]

    def test_an_override_replaces_the_whole_day_including_its_overnight_window(self) -> None:
        global_hours = only(monday=[window("08:00", "09:00"), window("22:00", "02:00")])
        task = candidate("t", 60, at(9, 12), active_hours_override={"monday": [window("10:00", "11:00")]})
        # Only 10:00-11:00 on Monday now; the 22:00 night is gone.
        assert starts(run([task], global_hours, now=at(6, 7))) == {"t": at(6, 10)}
        full = candidate("u", 180, at(9, 12), active_hours_override={"monday": [window("10:00", "11:00")]})
        assert run([full], global_hours, now=at(6, 7)).unschedulable_task_ids == ("u",)

    def test_an_override_can_add_an_overnight_window_to_a_plain_global_day(self) -> None:
        plain = only(monday=[window("09:00", "17:00")], tuesday=[window("09:00", "17:00")])
        task = candidate("t", 120, at(7, 12), active_hours_override={"monday": [window("23:00", "03:00")]})
        assert starts(run([task], plain, now=at(6, 18))) == {"t": at(6, 23)}


class TestWindowValidationEdges:
    @pytest.mark.parametrize(
        ("windows", "valid"),
        [
            ([("00:00", "23:59")], True),
            ([("00:00", "06:00"), ("22:00", "00:00")], True),  # early morning + a night ending at midnight
            ([("06:00", "05:59")], True),
            ([("22:00", "02:00"), ("02:00", "03:00")], True),  # meets the overnight window's end next date: no overlap today
            ([("08:00", "12:00"), ("12:00", "13:00"), ("13:00", "14:00")], True),
            ([("22:00", "02:00"), ("21:00", "23:00")], False),
            ([("22:00", "02:00"), ("23:59", "00:30")], False),
            ([("00:00", "00:00")], False),
            ([("08:00", "10:00"), ("09:59", "11:00")], False),
        ],
    )
    def test_which_day_lists_are_acceptable(self, windows: list[tuple[str, str]], valid: bool) -> None:
        day = [window(start, end) for start, end in windows]
        assert (validate_day_windows(day) is None) is valid


class TestBudgetsAcrossMidnight:
    def test_an_event_straddling_midnight_counts_on_both_dates(self) -> None:
        event = [Obstacle(start=at(6, 23), end=at(7, 1))]
        assert committed_minutes_for_day(date(2026, 4, 6), event, NY) == 60
        assert committed_minutes_for_day(date(2026, 4, 7), event, NY) == 60

    def test_that_event_uses_up_the_next_dates_budget_before_a_task_does(self) -> None:
        event = [Obstacle(start=at(6, 23), end=at(7, 1))]
        budget = {**no_budget(), "tuesday": 90}
        # 30 minutes of Tuesday's budget are left: a 60-minute task starting at 00:30 would put 90 more on it.
        assert first_slot(30, NIGHT, start=at(7, 1), end=at(7, 2), obstacles=event, daily_time_budget_minutes=budget) == at(7, 1)
        assert first_slot(45, NIGHT, start=at(7, 1), end=at(7, 2), obstacles=event, daily_time_budget_minutes=budget) is None

    def test_strict_enforcement_leaves_a_split_task_unplaced_where_soft_overrides(self) -> None:
        budget = {**no_budget(), "monday": 30, "tuesday": 20}
        task = [candidate("t", 60, at(7, 3))]
        strict = run(task, NIGHT, now=at(6, 12), daily_time_budget_minutes=budget, budget_enforcement="strict")
        soft = run(task, NIGHT, now=at(6, 12), daily_time_budget_minutes=budget, budget_enforcement="soft")
        assert strict.unschedulable_task_ids == ("t",)
        (placement,) = soft.placements
        assert placement.budget_overridden is True

    def test_a_blocked_grid_point_in_the_only_kind_split_leaves_nothing(self) -> None:
        budget = {**no_budget(), "monday": 30, "tuesday": 30}
        pinch = [Obstacle(start=at(6, 23, 30), end=at(6, 23, 45))]
        # 23:30 is the only start that splits 60 minutes 30/30; 23:45 would put 45 on Tuesday.
        assert first_slot(60, NIGHT, start=at(6, 12), end=at(7, 12), obstacles=pinch, daily_time_budget_minutes=budget) is None
        # ...so next Monday's night, same shape, is where it lands once the deadline allows.
        assert first_slot(60, NIGHT, start=at(6, 12), end=at(14, 12), obstacles=pinch, daily_time_budget_minutes=budget) == at(
            13, 23, 30
        )


# --- A brute-force oracle -------------------------------------------------------------------


def _oracle_first_slot(
    duration: int,
    hours: ActiveHoursMap,
    blackouts: list[BlackoutDate],
    obstacles: list[Obstacle],
    not_before: datetime,
    not_after: datetime,
) -> datetime | None:
    """The earliest 15-minute-grid start whose every minute is inside some window (read the
    plain way: a window belongs to the date that declares it and may end on the next), not on a
    blacked-out date, and clear of obstacles. Computed one minute at a time, in UTC."""

    def allowed(moment: datetime) -> bool:
        if any(b.start <= moment.date() <= b.end for b in blackouts):
            return False
        for declaring in (moment.date() - timedelta(days=1), moment.date()):
            for w in hours.get(day_name(declaring)) or ():
                begins = datetime.combine(declaring, w.start, tzinfo=UTC)
                ends_on = declaring if w.end > w.start else declaring + timedelta(days=1)
                if begins <= moment < datetime.combine(ends_on, w.end, tzinfo=UTC):
                    return True
        return False

    def free(moment: datetime) -> bool:
        return all(not (o.start <= moment < o.end) for o in obstacles)

    cursor = not_before.replace(second=0, microsecond=0)
    while cursor.minute % 15 or cursor < not_before:
        cursor += timedelta(minutes=1)
    while cursor + timedelta(minutes=duration) <= not_after:
        if all(allowed(cursor + timedelta(minutes=m)) and free(cursor + timedelta(minutes=m)) for m in range(duration)):
            return cursor
        cursor += timedelta(minutes=15)
    return None


def _random_week(rng: random.Random):  # type: ignore[no-untyped-def]
    clock = [time(h, m) for h in range(24) for m in (0, 15, 30, 45)]
    hours: dict[str, list[ActiveHoursWindow] | None] = {}
    for day in DAY_NAMES:
        if rng.random() < 0.2:
            hours[day] = None
            continue
        picked: list[ActiveHoursWindow] = []
        for _ in range(rng.choice([1, 1, 2, 3])):
            start, end = rng.sample(clock, 2)
            picked.append(ActiveHoursWindow(start=start, end=end))
        hours[day] = picked if validate_day_windows(picked) is None else [picked[0]]
    base = datetime(2026, 4, 6, tzinfo=UTC)
    blackouts = [
        BlackoutDate(start=base.date() + timedelta(days=d), end=base.date() + timedelta(days=d))
        for d in rng.sample(range(10), rng.choice([0, 0, 1, 2]))
    ]
    obstacles = []
    for _ in range(rng.randrange(0, 7)):
        begin = base + timedelta(minutes=15 * rng.randrange(0, 4 * 24 * 9))
        obstacles.append(Obstacle(start=begin, end=begin + timedelta(minutes=15 * rng.randrange(1, 17))))
    not_before = base + timedelta(minutes=rng.randrange(0, 60 * 30))
    duration = rng.choice([15, 30, 45, 60, 90, 120, 240, 480])
    return hours, blackouts, obstacles, not_before, duration


class TestAgainstABruteForceOracle:
    @pytest.mark.parametrize("seed", range(60))
    def test_the_first_free_slot_is_the_one_a_minute_by_minute_scan_finds(self, seed: int) -> None:
        hours, blackouts, obstacles, not_before, duration = _random_week(random.Random(seed))
        deadline = datetime(2026, 4, 6, tzinfo=UTC) + timedelta(days=10)
        expected = _oracle_first_slot(duration, hours, blackouts, obstacles, not_before, deadline)
        actual = first_slot(duration, hours, start=not_before, end=deadline, excluded_dates=blackouts, obstacles=obstacles)
        assert actual == expected

    @pytest.mark.parametrize("seed", range(30))
    def test_a_full_pass_never_double_books_or_leaves_the_allowed_time(self, seed: int) -> None:
        rng = random.Random(1000 + seed)
        hours, blackouts, obstacles, not_before, _ = _random_week(rng)
        deadline = datetime(2026, 4, 6, tzinfo=UTC) + timedelta(days=10)
        tasks = [
            candidate(f"t{i}", rng.choice([30, 60, 90, 180]), deadline - timedelta(hours=rng.randrange(0, 48))) for i in range(6)
        ]
        result = run(tasks, hours, now=not_before, blackout_dates=blackouts, obstacles=obstacles)

        placed = [(p, next(t for t in tasks if t.id == p.task_id)) for p in result.placements]
        spans = [(p.scheduled_start, p.scheduled_start + timedelta(minutes=t.estimated_duration_minutes)) for p, t in placed]
        # Every placed task is on the grid, after `now`, before its own deadline, and inside allowed time...
        for (start, end), (_, task) in zip(spans, placed, strict=True):
            assert start.minute % 15 == 0 and start >= not_before and end <= task.deadline
            assert (
                _oracle_first_slot(
                    task.estimated_duration_minutes,
                    hours,
                    blackouts,
                    [],
                    start,
                    start + timedelta(minutes=task.estimated_duration_minutes),
                )
                == start
            )
        # ...and clear of every obstacle and of every other placement.
        busy = [(o.start, o.end) for o in obstacles]
        for index, (start, end) in enumerate(spans):
            assert all(end <= other_start or other_end <= start for other_start, other_end in busy)
            assert all(end <= s or e <= start for s, e in spans[:index])
        assert {p.task_id for p, _ in placed} | set(result.unschedulable_task_ids) == {t.id for t in tasks}
