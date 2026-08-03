"""Auth domain helpers: pure functions for credential token parsing."""

from base64 import b64decode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


def classify_expiry(expires_at: datetime, now: datetime | None = None) -> str:
    """Classify a registry's credential expiry status.

    Mirrors the 1-hour warning threshold used in infra/credentials.py check_credentials.

    Returns:
        "EXPIRED" if now >= expires_at.
        "EXPIRING" if now >= expires_at - 1 hour.
        "VALID" otherwise.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    if now >= expires_at:
        return "EXPIRED"

    if now >= expires_at - timedelta(hours=1):
        return "EXPIRING"

    return "VALID"


@dataclass(frozen=True)
class TrackedRegistryStatus:
    """Expiry status for a single registry tracked in margot's credentials file."""

    hostname: str
    expires_at: datetime
    remaining: timedelta
    status: str


@dataclass(frozen=True)
class AuthStatusResult:
    """Structured result of the auth status check.

    tracked: registries tracked in margot's credentials file, with computed status.
    oras_only: registries present in the oras-py credential store but not tracked
        by margot (expiry unknown).
    """

    tracked: list[TrackedRegistryStatus]
    oras_only: list[str]
