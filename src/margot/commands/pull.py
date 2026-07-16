"""Pull command: retrieve OCI artifact layers to a local directory."""

from rich import print as rprint
from typer import Argument, Exit, Option, echo

from margot.services import pull as pull_service


def pull(
    uri: str = Argument(..., help="Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)"),
    output: str = Option(".", "--output", "-o", help="Output directory (default: current directory)."),
) -> None:
    """
    Pull OCI artifact layers to a local directory.

    URI is the full OCI reference: registry/repository:tag
    """
    try:
        paths = pull_service.pull_artifact(uri, outdir=output)
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
