from importlib.metadata import PackageNotFoundError, version

from rich import print as rprint
from typer import Exit, Option, Typer, echo

from margot.commands.fetch import fetch


def get_version() -> str:
    try:
        return version("margot")
    except PackageNotFoundError:
        return "unknown"


app = Typer(name="margot", help="Margo application package developer CLI.", no_args_is_help=True)

# Register commands
app.command()(fetch)


# TODO(@karnarokEpoch): Remove smoke cmd
@app.command()
def hello() -> None:
    """Say hello (smoke test)."""
    rprint("[bold green]margot[/bold green] is working!")


# TODO(@karnarokEpoch): Move version cmd to cmd folder
@app.callback(invoke_without_command=True)
def _version(
    version_flag: bool = Option(False, "--version", "-v", help="Print version and exit.", is_eager=True),
) -> None:
    if version_flag:
        echo(f"margot {get_version()}")
        raise Exit


if __name__ == "__main__":
    app()
