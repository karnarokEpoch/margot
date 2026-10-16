"""Global CLI options: version, verbosity, and color flags."""

from os import environ

from typer import Exit, Option, echo

from margot.commands.version import get_version
from margot.console import set_debug, set_json, set_no_color, set_verbose


def global_options(
    version_flag: bool = Option(False, "--version", "-V", help="Print version and exit.", is_eager=True),
    verbose: bool = Option(False, "--verbose", "-v", help="Enable verbose output (step-level info)."),
    debug: bool = Option(False, "--debug", "-d", help="Enable debug output (infra-level detail, implies --verbose)."),
    no_color: bool = Option(False, "--no-color", help="Disable color in terminal output."),
) -> None:
    """Register global CLI options.

    Handles version output and sets verbosity, JSON, and color flags for the application.
    Called once at startup via app.callback().
    """
    set_json(False)
    set_no_color(no_color or "NO_COLOR" in environ)

    if debug:
        set_debug(True)
    elif verbose:
        set_verbose(True)
    else:
        set_debug(False)
        set_verbose(False)

    if version_flag:
        echo(f"margot {get_version()}")
        raise Exit()  # noqa: RSE102 - Exit class must be instantiated
