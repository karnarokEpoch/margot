"""Global CLI options: version, verbose, and debug flags."""

from typer import Exit, Option, echo

from margot.commands.version import get_version
from margot.console import set_debug, set_verbose


def global_options(
    version_flag: bool = Option(False, "--version", "-V", help="Print version and exit.", is_eager=True),
    verbose: bool = Option(False, "--verbose", "-v", help="Enable verbose output (step-level info)."),
    debug: bool = Option(False, "--debug", "-d", help="Enable debug output (infra-level detail, implies --verbose)."),
) -> None:
    """Register global CLI options.

    Handles version output and sets verbosity flags for the application.
    Called once at startup via app.callback().
    """
    if debug:
        set_debug(True)
    elif verbose:
        set_verbose(True)

    if version_flag:
        echo(f"margot {get_version()}")
        raise Exit()  # noqa: RSE102 - Exit class must be instantiated
