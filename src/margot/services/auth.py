"""Auth service: orchestrate login/logout for OCI registries."""

from datetime import UTC, datetime, timedelta

from margot import console
from margot.infra import credentials as creds_infra
from margot.infra import oci


def login(
    registry: str,
    username: str,
    password: str,
    *,
    save_expiry: bool = False,
    expiry_hours: int = 12,
) -> None:
    """Login to an OCI registry.

    Steps:
    1. Create OrasClient and call login().
    2. If save_expiry: compute expires_at = now + expiry_hours, persist to credentials file.
    3. Emit console.info on step completion.
    """
    console.info(f"Logging in to {registry} as {username}.")
    client = oci.OrasClient()
    client.login(hostname=registry, username=username, password=password)

    if save_expiry:
        expires_at = datetime.now(tz=UTC) + timedelta(hours=expiry_hours)
        creds_infra.save_expiry(registry, expires_at)
        console.info(f"Expiry saved: {expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')}.")

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
