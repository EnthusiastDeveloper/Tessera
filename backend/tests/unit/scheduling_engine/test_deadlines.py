"""Unit tests for app.scheduling_engine.deadlines.is_deadline_elapsed. See design doc §6.7."""

from app.scheduling_engine.deadlines import is_deadline_elapsed
from tests.fixtures.scheduling import ny


def test_deadline_in_the_future_has_not_elapsed() -> None:
    deadline = ny(2026, 3, 2, 17, 0)
    now = ny(2026, 3, 1, 8, 0)
    assert is_deadline_elapsed(deadline, now) is False


def test_deadline_exactly_now_has_elapsed() -> None:
    moment = ny(2026, 3, 2, 17, 0)
    assert is_deadline_elapsed(moment, moment) is True


def test_deadline_in_the_past_has_elapsed() -> None:
    # Example K: "Renew passport" deadline Mon 2026-03-02 17:00, now Tue 2026-03-03 08:00.
    deadline = ny(2026, 3, 2, 17, 0)
    now = ny(2026, 3, 3, 8, 0)
    assert is_deadline_elapsed(deadline, now) is True
