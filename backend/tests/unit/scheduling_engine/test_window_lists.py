"""Windows per day and overnight windows (design doc §3.7, §6.2, §6.8, §6.10; Rev 13).

Mon 2026-03-02 .. Sun 2026-03-08, New York. A day holds a list of windows; a window whose
`end` is before its `start` runs overnight; a blackout date cuts at midnight; budgets count
by the calendar date the time falls on.
"""

from datetime import timedelta

from app.scheduling_engine.calendar_rules import eligible_intervals, validate_day_windows
from app.scheduling_engine.feasibility import validate_feasible_duration
from app.scheduling_engine.grid import usable_minutes
from app.scheduling_engine.placement import find_first_free_slot, schedule_pending_flexible_tasks
from app.scheduling_engine.repair import PlacedFlexibleTask, placements_that_no_longer_fit
from app.scheduling_engine.types import BlackoutDate, FlexibleTaskCandidate, Obstacle
from tests.fixtures.scheduling import NY, no_budget, ny, ny_date, window


def _slot(duration: int, hours: dict, *, start=ny(2026, 3, 2, 0, 0), end=ny(2026, 3, 9, 0, 0), **kwargs):  # type: ignore[no-untyped-def]
    arguments = {
        "duration_minutes": duration,
        "not_before": start,
        "not_after": end,
        "allowed_hours": hours,
        "excluded_dates": [],
        "daily_time_budget_minutes": no_budget(),
        "obstacles": [],
    }
    arguments.update(kwargs)
    return find_first_free_slot(**arguments)


class TestValidateDayWindows:
    def test_a_split_day_and_an_overnight_window_are_valid(self) -> None:
        assert validate_day_windows([window("08:00", "12:00"), window("18:00", "22:00")]) is None
        assert validate_day_windows([window("22:00", "02:00")]) is None
        # The overnight window ends on the NEXT date, so it doesn't collide with an early one today.
        assert validate_day_windows([window("22:00", "02:00"), window("01:00", "03:00")]) is None

    def test_windows_meeting_end_to_start_are_valid(self) -> None:
        assert validate_day_windows([window("08:00", "12:00"), window("12:00", "13:00")]) is None

    def test_a_window_with_no_length_is_rejected(self) -> None:
        assert "same time" in (validate_day_windows([window("09:00", "09:00")]) or "")

    def test_overlapping_windows_on_one_day_are_rejected_in_any_order(self) -> None:
        assert validate_day_windows([window("08:00", "12:00"), window("11:00", "14:00")]) is not None
        assert validate_day_windows([window("11:00", "14:00"), window("08:00", "12:00")]) is not None
        # An overnight window running into a later window of the same day.
        assert validate_day_windows([window("22:00", "02:00"), window("23:00", "23:30")]) is not None

    def test_a_window_nested_inside_another_is_rejected(self) -> None:
        assert validate_day_windows([window("08:00", "18:00"), window("09:00", "10:00")]) is not None


class TestEligibleIntervals:
    def test_a_split_day_gives_two_stretches(self) -> None:
        hours = {"monday": [window("08:00", "10:00"), window("18:00", "20:00")]}
        assert eligible_intervals(ny_date(2026, 3, 2), ny_date(2026, 3, 2), hours, [], NY) == [
            (ny(2026, 3, 2, 8), ny(2026, 3, 2, 10)),
            (ny(2026, 3, 2, 18), ny(2026, 3, 2, 20)),
        ]

    def test_an_overnight_window_ends_on_the_next_date(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        assert eligible_intervals(ny_date(2026, 3, 2), ny_date(2026, 3, 2), hours, [], NY) == [
            (ny(2026, 3, 2, 22), ny(2026, 3, 3, 2))
        ]

    def test_the_day_before_the_range_can_spill_into_it(self) -> None:
        hours = {"sunday": [window("23:00", "03:00")]}
        assert eligible_intervals(ny_date(2026, 3, 9), ny_date(2026, 3, 9), hours, [], NY) == [
            (ny(2026, 3, 8, 23), ny(2026, 3, 9, 3))
        ]

    def test_an_overnight_window_and_the_next_mornings_window_merge(self) -> None:
        hours = {"monday": [window("22:00", "02:00")], "tuesday": [window("02:00", "08:00")]}
        assert eligible_intervals(ny_date(2026, 3, 2), ny_date(2026, 3, 3), hours, [], NY) == [
            (ny(2026, 3, 2, 22), ny(2026, 3, 3, 8))
        ]

    def test_a_blackout_cuts_at_midnight_not_at_the_window(self) -> None:
        hours = {"monday": [window("22:00", "02:00")], "tuesday": [window("09:00", "10:00")]}
        tuesday_off = [BlackoutDate(start=ny_date(2026, 3, 3), end=ny_date(2026, 3, 3))]
        assert eligible_intervals(ny_date(2026, 3, 2), ny_date(2026, 3, 3), hours, tuesday_off, NY) == [
            (ny(2026, 3, 2, 22), ny(2026, 3, 3, 0))
        ]
        monday_off = [BlackoutDate(start=ny_date(2026, 3, 2), end=ny_date(2026, 3, 2))]
        assert eligible_intervals(ny_date(2026, 3, 2), ny_date(2026, 3, 3), hours, monday_off, NY) == [
            (ny(2026, 3, 3, 0), ny(2026, 3, 3, 2)),
            (ny(2026, 3, 3, 9), ny(2026, 3, 3, 10)),
        ]

    def test_an_excluded_day_contributes_nothing(self) -> None:
        assert eligible_intervals(ny_date(2026, 3, 2), ny_date(2026, 3, 2), {"monday": None}, [], NY) == []


class TestPlacement:
    def test_a_full_first_window_moves_the_task_to_the_second(self) -> None:
        hours = {"monday": [window("08:00", "10:00"), window("18:00", "20:00")]}
        busy = [Obstacle(start=ny(2026, 3, 2, 8), end=ny(2026, 3, 2, 10))]
        assert _slot(60, hours, obstacles=busy) == ny(2026, 3, 2, 18, 0)

    def test_a_task_may_use_a_window_that_opens_later_in_the_day(self) -> None:
        hours = {"monday": [window("08:00", "10:00"), window("18:00", "20:00")]}
        assert _slot(60, hours, start=ny(2026, 3, 2, 11, 0)) == ny(2026, 3, 2, 18, 0)

    def test_an_overnight_window_places_after_midnight(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        busy = [Obstacle(start=ny(2026, 3, 2, 22), end=ny(2026, 3, 3, 0))]
        assert _slot(60, hours, obstacles=busy) == ny(2026, 3, 3, 0, 0)

    def test_a_task_may_straddle_midnight_inside_an_overnight_window(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        busy = [Obstacle(start=ny(2026, 3, 2, 22), end=ny(2026, 3, 2, 23, 30))]
        slot = _slot(90, hours, obstacles=busy)
        assert slot == ny(2026, 3, 2, 23, 30)  # 23:30-01:00

    def test_sundays_overnight_window_spills_into_monday(self) -> None:
        hours = {"sunday": [window("23:00", "03:00")]}
        assert _slot(60, hours, start=ny(2026, 3, 9, 0, 0), end=ny(2026, 3, 10, 0, 0)) == ny(2026, 3, 9, 0, 0)

    def test_an_overnight_window_runs_out_at_its_end(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        assert _slot(60, hours, start=ny(2026, 3, 3, 1, 30), end=ny(2026, 3, 3, 12, 0)) is None

    def test_a_blackout_cuts_a_straddling_task_off_at_midnight(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        tuesday_off = [BlackoutDate(start=ny_date(2026, 3, 3), end=ny_date(2026, 3, 3))]
        # 23:30-00:30 would touch the blacked-out Tuesday, so only starts that finish by midnight work.
        assert _slot(60, hours, excluded_dates=tuesday_off) == ny(2026, 3, 2, 22, 0)
        assert _slot(150, hours, excluded_dates=tuesday_off) is None

    def test_a_budget_counts_each_calendar_date_a_task_touches(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        budget = {**no_budget(), "monday": 30, "tuesday": 30}
        # 22:00 would put 60 minutes on Monday; only 23:30-00:30 splits 30 and 30 within both caps.
        assert _slot(60, hours, daily_time_budget_minutes=budget) == ny(2026, 3, 2, 23, 30)
        # Tuesday already holds 20 committed minutes, so no split of 60 fits any more.
        busy = [Obstacle(start=ny(2026, 3, 3, 1, 0), end=ny(2026, 3, 3, 1, 20))]
        assert _slot(60, hours, daily_time_budget_minutes=budget, obstacles=busy) is None

    def test_a_date_without_a_budget_is_not_capped(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        budget = {**no_budget(), "tuesday": 30}
        busy = [Obstacle(start=ny(2026, 3, 3, 0, 0), end=ny(2026, 3, 3, 0, 20))]
        assert _slot(60, hours, daily_time_budget_minutes=budget, obstacles=busy) == ny(2026, 3, 2, 22, 0)

    def test_pass_two_picks_the_date_with_the_least_overage_across_an_overnight_window(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        budget = {**no_budget(), "monday": 30, "tuesday": 20}
        candidate = FlexibleTaskCandidate(id="t", deadline=ny(2026, 3, 3, 3, 0), priority=2, estimated_duration_minutes=60)
        result = schedule_pending_flexible_tasks(
            [candidate],
            now=ny(2026, 3, 2, 12, 0),
            active_hours=hours,
            blackout_dates=[],
            daily_time_budget_minutes=budget,
            budget_enforcement="soft",
            obstacles=[],
        )
        (placement,) = result.placements
        assert placement.budget_overridden is True
        assert placement.scheduled_start == ny(2026, 3, 2, 22, 0)  # 30 minutes over on Monday beats 40 over on Tuesday


class TestFeasibility:
    def test_a_task_fits_an_overnight_window_longer_than_any_same_day_one(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        assert validate_feasible_duration(240, hours) is True
        assert validate_feasible_duration(241, hours) is False

    def test_split_windows_are_measured_separately(self) -> None:
        hours = {"monday": [window("08:00", "10:00"), window("18:00", "21:00")]}
        assert validate_feasible_duration(180, hours) is True
        assert validate_feasible_duration(181, hours) is False

    def test_windows_that_run_into_each_other_across_midnight_count_as_one(self) -> None:
        hours = {"monday": [window("22:00", "02:00")], "tuesday": [window("02:00", "08:00")]}
        assert validate_feasible_duration(600, hours) is True  # 22:00-08:00
        assert validate_feasible_duration(601, hours) is False

    def test_sundays_overnight_window_joins_mondays_morning(self) -> None:
        hours = {"sunday": [window("22:00", "02:00")], "monday": [window("02:00", "05:00")]}
        assert validate_feasible_duration(420, hours) is True  # 22:00-05:00

    def test_usable_minutes_of_an_overnight_window(self) -> None:
        assert usable_minutes(window("22:00", "02:00")) == 240
        assert usable_minutes(window("22:07", "02:00")) == 225
        assert usable_minutes(window("09:00", "09:00")) == 0


class TestRepair:
    def _placed(self, start, minutes=60):  # type: ignore[no-untyped-def]
        return PlacedFlexibleTask(
            id="t", start=start, end=start + timedelta(minutes=minutes), deadline=ny(2026, 3, 10), priority=2
        )

    def _check(self, task, hours, **overrides):  # type: ignore[no-untyped-def]
        arguments = {
            "active_hours": hours,
            "blackout_dates": [],
            "daily_time_budget_minutes": no_budget(),
            "budget_enforcement": "soft",
            "other_obstacles": [],
        }
        arguments.update(overrides)
        return placements_that_no_longer_fit([task], **arguments)

    def test_a_task_inside_an_overnight_window_still_fits_even_across_midnight(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        assert self._check(self._placed(ny(2026, 3, 2, 23, 30)), hours) == ()

    def test_removing_the_overnight_window_strands_it(self) -> None:
        hours = {"monday": [window("22:00", "23:00")]}
        assert self._check(self._placed(ny(2026, 3, 2, 23, 30)), hours) == ("t",)

    def test_a_task_between_two_windows_of_a_split_day_no_longer_fits(self) -> None:
        hours = {"monday": [window("08:00", "10:00"), window("18:00", "20:00")]}
        assert self._check(self._placed(ny(2026, 3, 2, 9, 30)), hours) == ("t",)  # runs past the first window
        assert self._check(self._placed(ny(2026, 3, 2, 18, 30)), hours) == ()

    def test_a_blackout_on_the_date_after_midnight_strands_a_straddling_task(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        tuesday_off = [BlackoutDate(start=ny_date(2026, 3, 3), end=ny_date(2026, 3, 3))]
        assert self._check(self._placed(ny(2026, 3, 2, 23, 30)), hours, blackout_dates=tuesday_off) == ("t",)

    def test_a_strict_budget_counts_a_straddling_task_on_both_dates(self) -> None:
        hours = {"monday": [window("22:00", "02:00")]}
        budget = {**no_budget(), "tuesday": 20}  # the task spends 30 minutes of Tuesday
        result = self._check(
            self._placed(ny(2026, 3, 2, 23, 30)), hours, daily_time_budget_minutes=budget, budget_enforcement="strict"
        )
        assert result == ("t",)
