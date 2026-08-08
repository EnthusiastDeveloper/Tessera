"""Unit tests for app.auth.cookie_signing. See architecture-plan §6 ("signed cookie")."""

from app.auth.cookie_signing import sign, unsign


def test_sign_then_unsign_round_trips() -> None:
    signed = sign("session-id-123", "secret-key")
    assert unsign(signed, "secret-key") == "session-id-123"


def test_tampered_session_id_is_rejected() -> None:
    signed = sign("session-id-123", "secret-key")
    session_id, signature = signed.rsplit(".", 1)
    tampered = f"tampered-id.{signature}"
    assert unsign(tampered, "secret-key") is None


def test_tampered_signature_is_rejected() -> None:
    signed = sign("session-id-123", "secret-key")
    assert unsign(signed + "0", "secret-key") is None


def test_wrong_secret_key_is_rejected() -> None:
    signed = sign("session-id-123", "secret-key")
    assert unsign(signed, "a-different-secret-key") is None


def test_malformed_cookie_value_is_rejected() -> None:
    assert unsign("no-dot-separator-here", "secret-key") is None
    assert unsign("", "secret-key") is None
