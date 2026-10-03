"""Configuration the optimization limits depend on (design doc §6.11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**env: object) -> Settings:
    return Settings(_env_file=None, secret_key="x", **env)  # type: ignore[call-arg, arg-type]


def test_the_optimization_limits_default_to_ten_and_thirty_seconds() -> None:
    settings = _settings()
    assert (settings.optimization_slow_after_seconds, settings.optimization_timeout_seconds) == (10, 30)


def test_they_can_be_configured() -> None:
    settings = _settings(optimization_slow_after_seconds=4, optimization_timeout_seconds=12)
    assert (settings.optimization_slow_after_seconds, settings.optimization_timeout_seconds) == (4, 12)


@pytest.mark.parametrize(("slow", "timeout"), [(10, 10), (10, 5), (0, 30), (5, 0)])
def test_a_timeout_that_does_not_exceed_the_notice_or_a_non_positive_value_is_rejected(slow: int, timeout: int) -> None:
    with pytest.raises(ValidationError):
        _settings(optimization_slow_after_seconds=slow, optimization_timeout_seconds=timeout)
