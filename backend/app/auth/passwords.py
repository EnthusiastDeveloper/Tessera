"""Password hashing via argon2id. See architecture-plan §6."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash `plain` with argon2id. Never store or log the plaintext value."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """True if `plain` matches `hashed`. Only `VerifyMismatchError` (wrong password) is
    treated as "false" - any other exception (e.g. a corrupted hash) propagates, since
    that indicates a real problem rather than a routine wrong-password attempt.
    """
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False
