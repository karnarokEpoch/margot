"""Auth domain helpers: pure functions for credential token parsing."""

from base64 import b64decode
from datetime import UTC, datetime
from json import loads


def parse_token_expiry(password: str) -> datetime | None:
    """
    Attempt to extract an expiry datetime from a base64-encoded credential token.

    Tries to decode the password as base64 JSON and read the 'expiration' field
    (Unix timestamp). Returns None on any failure — callers must treat None as
    "no expiry detected" and proceed without expiry tracking.

    This handles ECR token format where the password is base64-encoded JSON
    containing an 'expiration' Unix timestamp at the top level.

    Args:
        password: The raw password string (may be base64 JSON or any other format).

    Returns:
        UTC-aware datetime if expiry is successfully parsed, None otherwise.
    """
    try:
        # Add padding if needed for base64
        padded = password + "=" * (4 - len(password) % 4) if len(password) % 4 else password
        decoded = b64decode(padded).decode("utf-8")
        data = loads(decoded)
        expiration = data.get("expiration")
        if expiration is None or not isinstance(expiration, int | float):
            return None
        return datetime.fromtimestamp(float(expiration), tz=UTC)
    except Exception:  # noqa: BLE001
        return None
