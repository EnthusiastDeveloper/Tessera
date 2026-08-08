"""In-memory login throttle. See architecture-plan §6 ("Login throttling").

**Documented choice (implementation-plan Stage 3 requires N be defined, not left
implicit):** 5 failed attempts within a 15-minute window locks out further attempts from
that key until the window elapses; a successful login resets the count immediately. The
key is `f"{client_ip}:{username}"`, not username alone - throttling by username alone
would let an attacker lock the real admin out of their own account from a different IP,
which is worse than the brute-force risk being mitigated.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

MAX_ATTEMPTS = 5
WINDOW = timedelta(minutes=15)


class LoginThrottle:
    """Single-process, in-memory failure tracker. `now` is always a caller-supplied
    parameter, never read internally, so this stays deterministic and testable.
    """

    def __init__(self) -> None:
        self._failures: dict[str, list[datetime]] = defaultdict(list)

    def is_locked_out(self, key: str, *, now: datetime) -> bool:
        recent = [attempt for attempt in self._failures[key] if now - attempt < WINDOW]
        self._failures[key] = recent
        return len(recent) >= MAX_ATTEMPTS

    def record_failure(self, key: str, *, now: datetime) -> None:
        self._failures[key].append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def clear_all(self) -> None:
        """Wipe every tracked key. Test-only - nothing in the app itself needs a global reset."""
        self._failures.clear()


login_throttle = LoginThrottle()
