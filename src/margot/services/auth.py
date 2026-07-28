"""Auth service: orchestrate login/logout for OCI registries."""

from datetime import UTC, datetime, timedelta

from margot import console
from margot.domain.auth import parse_token_expiry
from margot.infra import credentials as creds_infra
from margot.infra import oci


def login(
    registry: str,
    username: str,
    password: str,
    *,
    expiry_hours: int | None = None,
) -> None:
    """Login to an OCI registry.

    Steps:
    1. Create OrasClient and call login().
    2. Resolve expiry: explicit --expiry-hours wins; fall back to auto-detected from token.
    3. If resolved, persist to credentials file.
    4. Emit console.info on step completion.
    """
    console.info(f"Logging in to {registry} as {username}.")
    client = oci.OrasClient()
    client.login(hostname=registry, username=username, password=password)

    # Resolve expiry: explicit flag wins; fall back to auto-detected from token
    resolved_expiry: datetime | None = None
    if expiry_hours is not None:
        resolved_expiry = datetime.now(tz=UTC) + timedelta(hours=expiry_hours)
        console.info(f"Using explicit expiry: {expiry_hours}h.")
    else:
        detected = parse_token_expiry(password)
        if detected is not None:
            resolved_expiry = detected
            console.info(f"Expiry auto-detected from token: {detected.strftime('%Y-%m-%dT%H:%M:%SZ')}.")

    if resolved_expiry is not None:
        creds_infra.save_expiry(registry, resolved_expiry)
        console.info(f"Expiry saved: {resolved_expiry.strftime('%Y-%m-%dT%H:%M:%SZ')}.")

    console.info("Login complete.")


def logout(registry: str) -> None:
    """Logout from an OCI registry.

    Steps:
    1. Create OrasClient and call logout().
    2. Remove expiry from credentials file (no-op if not present).
    3. Emit console.info on step completion.
    """
    console.info(f"Logging out from {registry}.")
    client = oci.OrasClient()
    client.logout(hostname=registry)
    creds_infra.remove_expiry(registry)
    console.info("Logout complete.")
