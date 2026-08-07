"""Unit tests for app.scheduling_engine.calendar_rules. See design doc §3.2, §3.7, §6.2."""

from app.scheduling_engine.calendar_rules import day_name, day_range, is_blacked_out, merge_active_hours
from app.scheduling_engine.types import BlackoutDate
from tests.fixtures.scheduling import every_day, ny_date, window


class TestDayName:
    def test_monday_through_sunday(self) -> None:
        # 2026-03-02 is a Monday.
        expected = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        for offset, name in enumerate(expected):
            assert day_name(ny_date(2026, 3, 2 + offset)) == name


class TestDayRange:
    def test_inclusive_of_both_ends(self) -> None:
        days = list(day_range(ny_date(2026, 3, 2), ny_date(2026, 3, 4)))
        assert days == [ny_date(2026, 3, 2), ny_date(2026, 3, 3), ny_date(2026, 3, 4)]

    def test_single_day(self) -> None:
        assert list(day_range(ny_date(2026, 3, 2), ny_date(2026, 3, 2))) == [ny_date(2026, 3, 2)]

    def test_empty_when_start_after_end(self) -> None:
        assert list(day_range(ny_date(2026, 3, 5), ny_date(2026, 3, 2))) == []


class TestIsBlackedOut:
    def test_day_inside_range(self) -> None:
        blackout = [BlackoutDate(start=ny_date(2026, 3, 10), end=ny_date(2026, 3, 12))]
        assert is_blacked_out(ny_date(2026, 3, 11), blackout) is True

    def test_boundaries_are_inclusive(self) -> None:
        blackout = [BlackoutDate(start=ny_date(2026, 3, 10), end=ny_date(2026, 3, 12))]
        assert is_blacked_out(ny_date(2026, 3, 10), blackout) is True
        assert is_blacked_out(ny_date(2026, 3, 12), blackout) is True

    def test_day_outside_range(self) -> None:
        blackout = [BlackoutDate(start=ny_date(2026, 3, 10), end=ny_date(2026, 3, 12))]
        assert is_blacked_out(ny_date(2026, 3, 9), blackout) is False
        assert is_blacked_out(ny_date(2026, 3, 13), blackout) is False

    def test_empty_list(self) -> None:
        assert is_blacked_out(ny_date(2026, 3, 11), []) is False

    def test_multiple_ranges(self) -> None:
        blackouts = [
            BlackoutDate(start=ny_date(2026, 1, 1), end=ny_date(2026, 1, 1), label="New Year"),
            BlackoutDate(start=ny_date(2026, 3, 10), end=ny_date(2026, 3, 12)),
        ]
        assert is_blacked_out(ny_date(2026, 3, 11), blackouts) is True
        assert is_blacked_out(ny_date(2026, 1, 1), blackouts) is True
        assert is_blacked_out(ny_date(2026, 6, 1), blackouts) is False


class TestMergeActiveHours:
    def test_none_override_inherits_global_untouched(self) -> None:
        global_hours = every_day("18:00", "21:00")
        assert merge_active_hours(global_hours, None) == global_hours

    def test_empty_override_inherits_global_untouched(self) -> None:
        global_hours = every_day("18:00", "21:00")
        assert merge_active_hours(global_hours, {}) == global_hours

    def test_partial_override_only_replaces_named_days(self) -> None:
        # Example B: override names only Tuesday. Every other day must keep the
        # global window - a whole-map replacement would wipe them out instead.
        global_hours = every_day("18:00", "21:00")
        override = {"tuesday": window("18:00", "22:30")}

        merged = merge_active_hours(global_hours, override)

        assert merged["tuesday"] == window("18:00", "22:30")
        assert merged["monday"] == window("18:00", "21:00")
        assert merged["wednesday"] == window("18:00", "21:00")
        assert merged["sunday"] == window("18:00", "21:00")

    def test_override_can_exclude_a_day_with_explicit_null(self) -> None:
        global_hours = every_day("18:00", "21:00")
        override = {"monday": None}

        merged = merge_active_hours(global_hours, override)

        assert merged["monday"] is None
        assert merged["tuesday"] == window("18:00", "21:00")

    def test_original_maps_are_not_mutated(self) -> None:
        global_hours = every_day("18:00", "21:00")
        override = {"tuesday": window("18:00", "22:30")}

        merge_active_hours(global_hours, override)

        assert global_hours["tuesday"] == window("18:00", "21:00")
        assert override == {"tuesday": window("18:00", "22:30")}
