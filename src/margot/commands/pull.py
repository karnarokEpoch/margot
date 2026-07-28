"""Pull command: retrieve OCI artifact layers to a local directory."""

from typing import Annotated

from typer import Argument, Option

from margot import console
from margot.domain.models import PackageType
from margot.services import pull as pull_service

_VALID_FORCE_TYPES = ("margo", "compose", "quadlet")


def pull(
    uri: str = Argument(..., help="Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)"),
    output: str = Option(".", "--output", "-o", help="Output directory (default: current directory)."),
    force: bool = Option(
        False, "--force", "-f", help="Bypass SemVer gate, malicious annotation checks, and allow non-standard artifact types."
    ),
    force_type: Annotated[
        str | None, Option("--force-type", help="Force artifact type interpretation (margo|compose|quadlet).")
    ] = None,
) -> None:
    """
    Pull OCI artifact layers to a local directory.

    URI is the full OCI reference: registry/repository:tag
    """
    resolved_force_type: PackageType | None = None

    if force_type is not None:
        if force_type not in _VALID_FORCE_TYPES:
            console.fatal(f"invalid --force-type '{force_type}'. Must be one of: {', '.join(_VALID_FORCE_TYPES)}")
        resolved_force_type = PackageType(force_type)

    if resolved_force_type is not None and not force:
        force = True
        console.warning("--force-type implies --force. Safety checks bypassed.")
    elif force and resolved_force_type is None:
        console.warning("--force is active. Safety checks bypassed.")

    try:
        paths = pull_service.pull_artifact(
            uri,
            outdir=output,
            force=force,
            force_type=resolved_force_type,
        )
        for path in paths:
            console.success(f"Pulled: {path}")
        if not paths:
            console.warning("No layers pulled.")
    except ValueError as e:
        console.fatal(str(e))
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Error pulling artifact: {e}")
