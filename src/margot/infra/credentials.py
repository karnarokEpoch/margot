"""Credentials file R/W and expiry checks for OCI registries."""

from datetime import UTC, datetime, timedelta
from json import JSONDecodeError, dumps
from json import load as json_load
from pathlib import Path
from tomllib import load

from margot import console

CREDENTIALS_FILE = Path.home() / ".config" / "margot" / "credentials.toml"
DOCKER_CONFIG_FILE = Path.home() / ".docker" / "config.json"


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
    - If now >= expires_at - 1 hour: emit console.warning (do not raise).
    """
    expires_at = load_expiry(registry, credentials_file)
    if expires_at is None:
        return

    now = datetime.now(tz=UTC)
    if now >= expires_at:
        msg = f"Credentials for {registry} have expired."
        raise CredentialsExpiredError(msg)

    if now >= expires_at - timedelta(hours=1):
        console.warning(f"Credentials for {registry} expire in less than 1 hour.")


def _write_credentials(registries: dict[str, str], credentials_file: Path) -> None:
    """Write credentials TOML file manually."""
    lines: list[str] = []
    for reg, expires_at in registries.items():
        lines.append(f'[registries."{reg}"]')
        lines.append(f'expires_at = "{expires_at}"')
        lines.append("")

    credentials_file.write_text("\n".join(lines))


def list_tracked(credentials_file: Path = CREDENTIALS_FILE) -> list[tuple[str, datetime]]:
    """List every registry tracked in the margot credentials file with its expiry.

    Returns [] if the file doesn't exist or has no registries. Registries without
    an expires_at field are skipped.
    """
    console.debug(f"Reading tracked registries from {credentials_file}.")
    if not credentials_file.exists():
        return []

    with credentials_file.open("rb") as f:
        data = load(f)

    registries = data.get("registries", {})
    result: list[tuple[str, datetime]] = []
    for hostname, entry in registries.items():
        expires_at_str = entry.get("expires_at")
        if expires_at_str is None:
            continue
        result.append((hostname, datetime.fromisoformat(expires_at_str)))

    return result


def list_oras_registries(docker_config_file: Path | None = None) -> list[str]:
    """List registry hostnames present in the oras-py/Docker credential store.

    Best-effort read: returns [] if the file doesn't exist, is malformed JSON,
    or has no 'auths' key. Never raises.
    """
    config_file = docker_config_file if docker_config_file is not None else DOCKER_CONFIG_FILE
    console.debug(f"Reading oras-py registries from {config_file}.")
    if not config_file.exists():
        return []

    try:
        with config_file.open("rb") as f:
            data = json_load(f)
    except JSONDecodeError:
        return []

    auths = data.get("auths", {})
    return list(auths.keys())


def remove_docker_config_entry(hostname: str, config_file: Path | None = None) -> None:
    """Remove a registry's credential entry from the oras-py/Docker config file.

    oras-py's ``AuthBackend.logout()`` only removes the entry from its in-memory
    ``_auth_config`` — it never persists that removal back to disk. This is the
    disk-persistence half of logout: it directly edits ``~/.docker/config.json``
    (the same file oras-py reads via ``load_configs()``), removing the ``auths``
    entry for ``hostname``.

    Best-effort: no-op if the file doesn't exist, is malformed JSON, or the
    hostname isn't present. Never raises. All other top-level keys (``credsStore``,
    ``credHelpers``, other registries) are preserved untouched.

    Args:
        hostname: Registry hostname to remove (e.g. 'public.ecr.aws').
        config_file: Path to the docker-style config file. Defaults to
            ``DOCKER_CONFIG_FILE`` (``~/.docker/config.json``).
    """
    path = config_file if config_file is not None else DOCKER_CONFIG_FILE
    console.debug(f"Removing {hostname} from {path}.")
    if not path.exists():
        return

    try:
        with path.open("rb") as f:
            data = json_load(f)
    except JSONDecodeError:
        console.debug(f"{path} is not valid JSON; skipping logout cleanup.")
        return

    auths = data.get("auths", {})
    if hostname not in auths:
        return

    del auths[hostname]
    data["auths"] = auths
    path.write_text(dumps(data, indent=2) + "\n")
