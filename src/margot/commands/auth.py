"""Auth commands: manage OCI registry credentials."""

import sys
from typing import Annotated

from typer import Option, Typer

from margot import config, console
from margot.services import auth as auth_service

app = Typer(name="auth", help="Manage OCI registry credentials.", no_args_is_help=True)


def _default_registry() -> str:
    """Resolve default registry from config or fallback."""
    return config.get("registry") or "public.ecr.aws"


@app.command()
def login(
    registry: Annotated[str | None, Option("--registry", "-r", help="Registry hostname.")] = None,
    username: Annotated[str | None, Option("--username", "-u", help="Username for authentication.")] = None,
    password_stdin: Annotated[bool, Option("--password-stdin", help="Read password from stdin.")] = False,
    save_expiry: Annotated[bool, Option("--save-expiry", help="Save credential expiry (12h) to credentials file.")] = False,
) -> None:
    """Login to an OCI registry."""
    resolved_registry = registry or _default_registry()

    if not username:
        console.fatal("Username required. Use --username.")

    if not password_stdin:
        console.fatal("Password required. Use --password-stdin.")

    password = sys.stdin.read().strip()
    if not password:
        console.fatal("Empty password received from stdin.")

    try:
        auth_service.login(
            registry=resolved_registry,
            username=username,
            password=password,
            save_expiry=save_expiry,
        )
        console.success(f"Logged in to {resolved_registry}.")
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Login failed: {e}")


@app.command()
def logout(
    registry: Annotated[str | None, Option("--registry", "-r", help="Registry hostname.")] = None,
) -> None:
    """Logout from an OCI registry."""
    resolved_registry = registry or _default_registry()

    try:
        auth_service.logout(registry=resolved_registry)
        console.success(f"Logged out from {resolved_registry}.")
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Logout failed: {e}")
