from importlib.metadata import PackageNotFoundError, version

from rich import print as rprint
from typer import Exit, Option, Typer, echo

try:
    __version__ = version("margot")
except PackageNotFoundError:
    __version__ = "unknown"

app = Typer(name="margot", help="Margo application package developer CLI.", no_args_is_help=True)


@app.command()
def hello() -> None:
    """Say hello (smoke test)."""
    rprint("[bold green]margot[/bold green] is working!")


@app.callback(invoke_without_command=True)
def _version(
    version: bool = Option(False, "--version", "-v", help="Print version and exit.", is_eager=True),
) -> None:
    if version:
        echo(f"margot {__version__}")
        raise Exit


if __name__ == "__main__":
    app()
