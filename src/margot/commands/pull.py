"""Pull command: retrieve OCI artifact layers to a local directory."""

from typing import Annotated

from rich import print as rprint
from typer import Argument, Exit, Option, echo

from margot.domain.models import PackageType
from margot.services import pull as pull_service

_VALID_FORCE_TYPES = ("margo", "compose", "quadlet")


def pull(
    uri: str = Argument(..., help="Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)"),
    output: str = Option(".", "--output", "-o", help="Output directory (default: current directory)."),
    force: bool = Option(False, "--force", "-f", help="Bypass SemVer gate, malicious annotation checks, and allow non-standard artifact types."),
    force_type: Annotated[str | None, Option("--force-type", help="Force artifact type interpretation (margo|compose|quadlet). Requires --force.")] = None,
) -> None:
    """
    Pull OCI artifact layers to a local directory.

    URI is the full OCI reference: registry/repository:tag
    """
    resolved_force_type: PackageType | None = None

    if force_type is not None:
        if force_type not in _VALID_FORCE_TYPES:
            echo(f"Error: invalid --force-type '{force_type}'. Must be one of: {', '.join(_VALID_FORCE_TYPES)}", err=True)
            raise Exit(1)
        resolved_force_type = PackageType(force_type)

    if force:
        rprint("[yellow]Warning: --force is active. Safety checks bypassed.[/yellow]")

    try:
        paths = pull_service.pull_artifact(
            uri,
            outdir=output,
            force=force,
            force_type=resolved_force_type,
        )
        for path in paths:
            rprint(f"[green]Pulled:[/green] {path}")
        if not paths:
            rprint("[yellow]No layers pulled.[/yellow]")
    except ValueError as e:
        echo(f"Error: {e}", err=True)
        raise Exit(1) from e
    except Exception as e:
        echo(f"Error pulling artifact: {e}", err=True)
        raise Exit(1) from e
