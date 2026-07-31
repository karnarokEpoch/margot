"""Credentials file R/W and expiry checks for OCI registries."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tomllib import load

from margot import console

CREDENTIALS_FILE = Path.home() / ".config" / "margot" / "credentials.toml"


class CredentialsExpiredError(Exception):
    """Raised when registry credentials are expired."""


def load_expiry(registry: str, credentials_file: Path = CREDENTIALS_FILE) -> datetime | None:
    """Read expiry timestamp for registry from credentials file.

    Returns None if not tracked.
    """
    if not credentials_file.exists():
        return None

    with credentials_file.open("rb") as f:
        data = load(f)

    registries = data.get("registries", {})
    entry = registries.get(registry)
    if entry is None:
        return None

    expires_at_str = entry.get("expires_at")
    if expires_at_str is None:
        return None

    return datetime.fromisoformat(expires_at_str)


def save_expiry(registry: str, expires_at: datetime, credentials_file: Path = CREDENTIALS_FILE) -> None:
    """Persist expiry timestamp for registry to credentials file."""
    credentials_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data
    existing: dict[str, dict[str, str]] = {}
    if credentials_file.exists():
        with credentials_file.open("rb") as f:
            data = load(f)
        registries = data.get("registries", {})
        for reg, entry in registries.items():
            if "expires_at" in entry:
                existing[reg] = entry["expires_at"]

    # Update the target registry
    existing[registry] = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Write back manually as TOML
    _write_credentials(existing, credentials_file)


def remove_expiry(registry: str, credentials_file: Path = CREDENTIALS_FILE) -> None:
    """Remove expiry entry for registry from credentials file. No-op if not present."""
    if not credentials_file.exists():
        return

    with credentials_file.open("rb") as f:
        data = load(f)

    registries = data.get("registries", {})
    if registry not in registries:
        return

    # Rebuild without the target registry
    existing: dict[str, str] = {}
    for reg, entry in registries.items():
        if reg != registry and "expires_at" in entry:
            existing[reg] = entry["expires_at"]

    _write_credentials(existing, credentials_file)


def check_credentials(registry: str, credentials_file: Path = CREDENTIALS_FILE) -> None:
    """Check if credentials for registry are expired or near-expiry.

    - If no expiry tracked: return silently (no tracking = no check).
    - If now >= expires_at: raise CredentialsExpiredError.
    - If now >= expires_at - 5min: emit console.warning (do not raise).
    """
    expires_at = load_expiry(registry, credentials_file)
    if expires_at is None:
        return

    now = datetime.now(tz=UTC)
    if now >= expires_at:
        msg = f"Credentials for {registry} have expired."
        raise CredentialsExpiredError(msg)

    if now >= expires_at - timedelta(minutes=5):
        console.warning(f"Credentials for {registry} expire in less than 5 minutes.")


def _write_credentials(registries: dict[str, str], credentials_file: Path) -> None:
    """Write credentials TOML file manually."""
    lines: list[str] = []
    for reg, expires_at in registries.items():
        lines.append(f'[registries."{reg}"]')
        lines.append(f'expires_at = "{expires_at}"')
        lines.append("")

    credentials_file.write_text("\n".join(lines))
