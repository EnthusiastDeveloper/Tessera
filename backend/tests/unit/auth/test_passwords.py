"""Unit tests for app.auth.passwords. See architecture-plan §6."""

from app.auth.passwords import hash_password, verify_password


def test_correct_password_verifies() -> None:
    hashed = hash_password("correcthorsebatterystaple")
    assert verify_password("correcthorsebatterystaple", hashed) is True


def test_wrong_password_is_rejected() -> None:
    hashed = hash_password("correcthorsebatterystaple")
    assert verify_password("wrong-password", hashed) is False


def test_hash_is_never_the_plaintext() -> None:
    hashed = hash_password("correcthorsebatterystaple")
    assert hashed != "correcthorsebatterystaple"


def test_two_hashes_of_the_same_password_differ() -> None:
    """argon2id salts each hash - two hashes of the same input must not be identical."""
    assert hash_password("correcthorsebatterystaple") != hash_password("correcthorsebatterystaple")
