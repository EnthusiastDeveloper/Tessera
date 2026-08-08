"""In-memory first-run setup token. See design doc §3.6, architecture-plan §6.

Held in memory only, never persisted - a process restart reissues it, which is
deliberate (a token that leaked but was never used should not stay valid indefinitely).
Compared in constant time so response timing can't leak how much of a guess matched.
"""

from __future__ import annotations

import secrets


class SetupTokenStore:
    """Single-process holder for the first-run setup token."""

    def __init__(self) -> None:
        self._token: str | None = None

    def issue(self) -> str:
        """Generate and hold a new token. Call once at startup while zero `User` rows exist."""
        self._token = secrets.token_urlsafe(32)
        return self._token

    def verify(self, candidate: str) -> bool:
        """Constant-time compare against the held token. False if none is currently active."""
        if self._token is None:
            return False
        return secrets.compare_digest(self._token, candidate)

    def invalidate(self) -> None:
        """Called the moment setup completes successfully - the token is single-use."""
        self._token = None

    @property
    def is_active(self) -> bool:
        return self._token is not None


setup_token_store = SetupTokenStore()
