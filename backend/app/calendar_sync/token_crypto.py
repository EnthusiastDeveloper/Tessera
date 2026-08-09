"""Fernet encryption for OAuth tokens at rest, keyed by `SECRET_KEY`. See design doc §3.5
("reference to secret storage, not raw tokens"), architecture-plan §6 ("Secrets at rest").

`app.db.models.oauth_token.OAuthTokenORM` stores only the ciphertext this module produces -
the data-access layer never sees a plaintext token.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class TokenDecryptionError(Exception):
    """Raised when ciphertext fails to decrypt - a wrong/rotated `SECRET_KEY`, or corrupt data."""


def _derive_fernet_key(secret_key: str) -> bytes:
    """`SECRET_KEY` is an arbitrary operator-chosen string (architecture-plan §7.1), not
    necessarily the 32 url-safe-base64-encoded bytes Fernet's constructor requires -
    SHA-256 deterministically derives a valid key from it, the same way every request
    needs the identical key without persisting a second secret anywhere.
    """
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext: str, *, secret_key: str) -> str:
    return Fernet(_derive_fernet_key(secret_key)).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, *, secret_key: str) -> str:
    try:
        return Fernet(_derive_fernet_key(secret_key)).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptionError("OAuth token ciphertext could not be decrypted with the current SECRET_KEY.") from exc


__all__ = ["TokenDecryptionError", "decrypt", "encrypt"]
