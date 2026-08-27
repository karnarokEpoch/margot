"""Margot CLI entry point."""

from typer import Typer

from margot.commands.auth import app as auth_app
from margot.commands.build import build_cmd
from margot.commands.fetch import fetch
from margot.commands.global_options import global_options
from margot.commands.pull import pull
from margot.commands.push import push_cmd
from margot.commands.verify import verify_cmd

app = Typer(
    name="margot",
    help="Margo application package developer CLI.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Register commands
app.command()(fetch)
app.command(name="build")(build_cmd)
app.command(name="push")(push_cmd)
app.command()(pull)
app.command(name="verify")(verify_cmd)

# Register subcommand groups
app.add_typer(auth_app, name="auth")

# Register global flags callback
app.callback(invoke_without_command=True)(global_options)


if __name__ == "__main__":
    app()
