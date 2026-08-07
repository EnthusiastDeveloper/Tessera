"""Unit tests for app.scheduling_engine.fixed_conflicts.check_fixed_conflict. See design doc §6.5."""

from app.scheduling_engine.fixed_conflicts import check_fixed_conflict
from app.scheduling_engine.types import Obstacle
from tests.fixtures.scheduling import ny


def test_no_obstacles_never_conflicts() -> None:
    assert check_fixed_conflict(ny(2026, 3, 2, 18, 0), ny(2026, 3, 2, 19, 0), []) is False


def test_overlapping_obstacle_conflicts() -> None:
    # Example A: "Date night" Mon 18:00-22:00 vs. a proposed 18:00-19:00 fixed task.
    obstacles = [Obstacle(start=ny(2026, 3, 2, 18, 0), end=ny(2026, 3, 2, 22, 0))]
    assert check_fixed_conflict(ny(2026, 3, 2, 18, 0), ny(2026, 3, 2, 19, 0), obstacles) is True


def test_partial_overlap_conflicts() -> None:
    obstacles = [Obstacle(start=ny(2026, 3, 2, 18, 30), end=ny(2026, 3, 2, 19, 30))]
    assert check_fixed_conflict(ny(2026, 3, 2, 18, 0), ny(2026, 3, 2, 19, 0), obstacles) is True


def test_non_overlapping_obstacle_does_not_conflict() -> None:
    obstacles = [Obstacle(start=ny(2026, 3, 2, 20, 0), end=ny(2026, 3, 2, 21, 0))]
    assert check_fixed_conflict(ny(2026, 3, 2, 18, 0), ny(2026, 3, 2, 19, 0), obstacles) is False


def test_touching_boundaries_do_not_conflict() -> None:
    # Obstacle ends exactly when the candidate starts - back-to-back, not overlapping.
    obstacles = [Obstacle(start=ny(2026, 3, 2, 17, 0), end=ny(2026, 3, 2, 18, 0))]
    assert check_fixed_conflict(ny(2026, 3, 2, 18, 0), ny(2026, 3, 2, 19, 0), obstacles) is False

    obstacles = [Obstacle(start=ny(2026, 3, 2, 19, 0), end=ny(2026, 3, 2, 20, 0))]
    assert check_fixed_conflict(ny(2026, 3, 2, 18, 0), ny(2026, 3, 2, 19, 0), obstacles) is False


def test_conflict_detected_among_several_obstacles() -> None:
    obstacles = [
        Obstacle(start=ny(2026, 3, 2, 6, 0), end=ny(2026, 3, 2, 7, 0)),
        Obstacle(start=ny(2026, 3, 2, 18, 30), end=ny(2026, 3, 2, 19, 30)),
        Obstacle(start=ny(2026, 3, 2, 22, 0), end=ny(2026, 3, 2, 23, 0)),
    ]
    assert check_fixed_conflict(ny(2026, 3, 2, 18, 0), ny(2026, 3, 2, 19, 0), obstacles) is True
