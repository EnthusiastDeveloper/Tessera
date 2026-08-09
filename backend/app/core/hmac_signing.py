"""Generic HMAC-SHA256 sign/verify for a short string value, keyed by a caller-supplied
secret. Lives in `app.core` deliberately - `app.auth` and `app.calendar_sync` are
independent siblings under the import-linter "Layering" contract (`backend/pyproject.toml`)
and neither may import the other, but both need the identical sign-and-compare_digest
pattern (the session cookie value, and the OAuth `state` parameter respectively). `app.core`
sits outside that contract entirely, so it's the shared home for both without violating it.
"""

from __future__ import annotations

import hmac
from hashlib import sha256


def sign(value: str, secret_key: str) -> str:
    """Produce `<value>.<hex hmac-sha256 signature>`. `value` must not itself contain a
    `.` - callers that need one should encode it differently (e.g. `:`-separated fields).
    """
    signature = hmac.new(secret_key.encode(), value.encode(), sha256).hexdigest()
    return f"{value}.{signature}"


def unsign(signed_value: str, secret_key: str) -> str | None:
    """Return the original value if the signature is valid, else `None`."""
    try:
        value, signature = signed_value.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret_key.encode(), value.encode(), sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    return value
