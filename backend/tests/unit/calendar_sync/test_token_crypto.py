"""Fernet round-trip tests for OAuth token encryption. See design doc §3.5, architecture-plan §6."""

from __future__ import annotations

import pytest

from app.calendar_sync.token_crypto import TokenDecryptionError, decrypt, encrypt


def test_round_trip_recovers_the_plaintext() -> None:
    ciphertext = encrypt("a-real-google-access-token", secret_key="test-secret-key-not-for-production-use")
    assert decrypt(ciphertext, secret_key="test-secret-key-not-for-production-use") == "a-real-google-access-token"


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    ciphertext = encrypt("super-secret-refresh-token", secret_key="k")
    assert "super-secret-refresh-token" not in ciphertext


def test_wrong_secret_key_fails_to_decrypt() -> None:
    ciphertext = encrypt("token", secret_key="key-one")
    with pytest.raises(TokenDecryptionError):
        decrypt(ciphertext, secret_key="key-two")


def test_two_encryptions_of_the_same_value_differ() -> None:
    """Fernet includes a random IV/nonce - two ciphertexts for the same plaintext should
    not be identical (defends against a naive/deterministic implementation slipping in).
    """
    first = encrypt("token", secret_key="k")
    second = encrypt("token", secret_key="k")
    assert first != second
