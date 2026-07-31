"""Auth commands: manage OCI registry credentials."""

from datetime import UTC, datetime
import sys
from typing import Annotated

from typer import Argument, Option, Typer

from margot import console
from margot.services import auth as auth_service

app = Typer(name="auth", help="Manage OCI registry credentials.", no_args_is_help=True)


def _format_expiry(expires_at: datetime) -> str:
    """Format time remaining until expiry as a human-readable string."""
    remaining = expires_at - datetime.now(tz=UTC)
    total_seconds = int(remaining.total_seconds())
    if total_seconds <= 0:
        return f"already expired ({expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')})"
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes:02d}m (expires {expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')})"


@app.command()
def login(
    registry: Annotated[str, Argument(help="Registry hostname (e.g. public.ecr.aws).")],
    username: Annotated[str | None, Option("--username", "-u", help="Username for authentication.")] = None,
    password_stdin: Annotated[bool, Option("--password-stdin", help="Read password from stdin.")] = False,
    expiry_hours: Annotated[
        int | None,
        Option(
            "--expiry-hours",
            help="Save credential expiry to credentials file. Provide the number of hours until expiry (e.g. 12 for ECR).",
        ),
    ] = None,
) -> None:
    """Login to an OCI registry."""
    if not username:
        console.fatal("Username required. Use --username.")

    if not password_stdin:
        console.fatal("Password required. Use --password-stdin.")

    password = sys.stdin.read().strip()
    if not password:
        console.fatal("Empty password received from stdin.")

    try:
        expires_at = auth_service.login(
            registry=registry,
            username=username,
            password=password,
            expiry_hours=expiry_hours,
        )
        console.success(f"Logged in to {registry}.")
        if expires_at is not None:
            console.success(f"Token expires in {_format_expiry(expires_at)}")
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Login failed: {e}")


@app.command()
def logout(
    registry: Annotated[str, Argument(help="Registry hostname (e.g. public.ecr.aws).")],
) -> None:
    """Logout from an OCI registry."""
    try:
        auth_service.logout(registry=registry)
        console.success(f"Logged out from {registry}.")
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Logout failed: {e}")
