"""Margot CLI entry point."""

from typer import Typer

from margot.commands.fetch import fetch
from margot.commands.version import version_callback

app = Typer(name="margot", help="Margo application package developer CLI.", no_args_is_help=True)

# Register commands
app.command()(fetch)

# Register global flags callback
app.callback(invoke_without_command=True)(version_callback)


if __name__ == "__main__":
    app()
