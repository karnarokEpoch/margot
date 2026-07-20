"""Margot CLI entry point."""

from typer import Typer

from margot.commands.fetch import fetch
from margot.commands.global_options import global_options
from margot.commands.pull import pull

app = Typer(name="margot", help="Margo application package developer CLI.", no_args_is_help=True)

# Register commands
app.command()(fetch)
app.command()(pull)

# Register global flags callback
app.callback(invoke_without_command=True)(global_options)


if __name__ == "__main__":
    app()
