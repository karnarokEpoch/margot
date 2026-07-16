"""Version command: print margot version."""

from importlib.metadata import PackageNotFoundError, version

from typer import Exit, Option, echo


def get_version() -> str:
    """Return the installed margot package version, or 'unknown' if not installed."""
    try:
        return version("margot")
    except PackageNotFoundError:
        return "unknown"


def version_callback(
    version_flag: bool = Option(False, "--version", "-v", help="Print version and exit.", is_eager=True),
) -> None:
    """Print margot version and exit."""
    if version_flag:
        echo(f"margot {get_version()}")
        raise Exit
