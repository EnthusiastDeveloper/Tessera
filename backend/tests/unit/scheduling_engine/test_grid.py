"""Unit tests for app.scheduling_engine.grid. See design doc §6.2 'Placement grid' and §6.8."""

from app.scheduling_engine.grid import ceil_to_grid, usable_minutes
from app.scheduling_engine.types import ActiveHoursWindow
from tests.fixtures.scheduling import hm, ny, window


class TestCeilToGrid:
    def test_already_on_grid_point_is_unchanged(self) -> None:
        assert ceil_to_grid(ny(2026, 3, 3, 21, 30), 15) == ny(2026, 3, 3, 21, 30)

    def test_exact_hour_is_unchanged(self) -> None:
        assert ceil_to_grid(ny(2026, 3, 2, 19, 0), 15) == ny(2026, 3, 2, 19, 0)

    def test_rounds_up_to_next_grid_point(self) -> None:
        # Example B: first free moment is 21:37, first grid point at/after is 21:45.
        assert ceil_to_grid(ny(2026, 3, 3, 21, 37), 15) == ny(2026, 3, 3, 21, 45)

    def test_rounds_up_across_the_hour(self) -> None:
        assert ceil_to_grid(ny(2026, 3, 3, 21, 50), 15) == ny(2026, 3, 3, 22, 0)

    def test_nonzero_seconds_past_a_grid_point_still_rounds_up(self) -> None:
        moment = ny(2026, 3, 3, 21, 30).replace(second=5)
        assert ceil_to_grid(moment, 15) == ny(2026, 3, 3, 21, 45)

    def test_custom_grid_size(self) -> None:
        assert ceil_to_grid(ny(2026, 3, 3, 21, 10), 30) == ny(2026, 3, 3, 21, 30)

    def test_already_grid_point_saturday_1130(self) -> None:
        # Example G: 11:30 is already a grid point.
        assert ceil_to_grid(ny(2026, 3, 7, 11, 30), 15) == ny(2026, 3, 7, 11, 30)


class TestUsableMinutes:
    def test_grid_aligned_start_uses_full_span(self) -> None:
        assert usable_minutes(window("18:00", "21:00"), 15) == 180

    def test_non_grid_aligned_start_measured_from_first_grid_point(self) -> None:
        # Example I grid variant: 18:07-21:00 -> usable from 18:15, not 18:07 -> 165 minutes.
        assert usable_minutes(window("18:07", "21:00"), 15) == 165

    def test_start_equals_end_is_zero(self) -> None:
        assert usable_minutes(window("18:00", "18:00"), 15) == 0

    def test_rounding_can_consume_the_entire_window(self) -> None:
        # Start rounds up to 21:00, which equals the window end -> nothing usable.
        assert usable_minutes(window("20:52", "21:00"), 15) == 0

    def test_zero_width_after_rounding_never_goes_negative(self) -> None:
        tiny = ActiveHoursWindow(start=hm("20:58"), end=hm("21:00"))
        assert usable_minutes(tiny, 15) == 0
