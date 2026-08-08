"""Unit tests for app.auth.setup_token. See design doc §3.6, architecture-plan §6."""

from app.auth.setup_token import SetupTokenStore


def test_no_token_active_before_issue() -> None:
    store = SetupTokenStore()
    assert store.is_active is False
    assert store.verify("anything") is False


def test_issued_token_verifies() -> None:
    store = SetupTokenStore()
    token = store.issue()
    assert store.is_active is True
    assert store.verify(token) is True


def test_wrong_token_is_rejected() -> None:
    store = SetupTokenStore()
    store.issue()
    assert store.verify("wrong-token") is False


def test_invalidate_makes_the_token_unusable() -> None:
    store = SetupTokenStore()
    token = store.issue()
    store.invalidate()
    assert store.is_active is False
    assert store.verify(token) is False


def test_reissuing_produces_a_different_token() -> None:
    """A restart before setup reissues, and the old token must not still work."""
    store = SetupTokenStore()
    first = store.issue()
    second = store.issue()
    assert first != second
    assert store.verify(first) is False
    assert store.verify(second) is True
