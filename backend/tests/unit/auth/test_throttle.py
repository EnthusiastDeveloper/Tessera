"""Unit tests for app.auth.throttle. See architecture-plan §6 ("Login throttling")."""

from datetime import UTC, datetime, timedelta

from app.auth.throttle import MAX_ATTEMPTS, WINDOW, LoginThrottle


def test_not_locked_out_before_max_attempts() -> None:
    throttle = LoginThrottle()
    now = datetime.now(UTC)
    for _ in range(MAX_ATTEMPTS - 1):
        throttle.record_failure("key", now=now)
    assert throttle.is_locked_out("key", now=now) is False


def test_locked_out_at_max_attempts() -> None:
    throttle = LoginThrottle()
    now = datetime.now(UTC)
    for _ in range(MAX_ATTEMPTS):
        throttle.record_failure("key", now=now)
    assert throttle.is_locked_out("key", now=now) is True


def test_lockout_expires_after_the_window() -> None:
    throttle = LoginThrottle()
    now = datetime.now(UTC)
    for _ in range(MAX_ATTEMPTS):
        throttle.record_failure("key", now=now)
    later = now + WINDOW + timedelta(seconds=1)
    assert throttle.is_locked_out("key", now=later) is False


def test_reset_clears_lockout() -> None:
    throttle = LoginThrottle()
    now = datetime.now(UTC)
    for _ in range(MAX_ATTEMPTS):
        throttle.record_failure("key", now=now)
    throttle.reset("key")
    assert throttle.is_locked_out("key", now=now) is False


def test_keys_are_independent() -> None:
    """Throttling by `f'{client_ip}:{username}'` - one attacker's key must not lock out another."""
    throttle = LoginThrottle()
    now = datetime.now(UTC)
    for _ in range(MAX_ATTEMPTS):
        throttle.record_failure("attacker-ip:admin", now=now)
    assert throttle.is_locked_out("legit-ip:admin", now=now) is False


def test_clear_all_resets_every_key() -> None:
    throttle = LoginThrottle()
    now = datetime.now(UTC)
    for _ in range(MAX_ATTEMPTS):
        throttle.record_failure("a", now=now)
        throttle.record_failure("b", now=now)
    throttle.clear_all()
    assert throttle.is_locked_out("a", now=now) is False
    assert throttle.is_locked_out("b", now=now) is False
