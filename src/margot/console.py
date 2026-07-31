"""Central output hub for margot CLI.

All terminal output goes through this module. Provides consistent formatting
and routing (stdout vs stderr) for success, warnings, info, debug, and fatal messages.

Verbosity is controlled by two module-level flags:
  - _verbose: Enables info() output (high-level step logs).
  - _debug: Enables debug() output (low-level infra calls). Implies _verbose.
"""

from datetime import UTC, datetime
from inspect import stack
from json import dumps
from os.path import relpath
import sys

from rich.console import Console
from typer import Exit

# Module-level console instances (for testing, may be replaced with mocks)
_stdout: Console | None = None
_stderr: Console | None = None
_verbose: bool = False
_debug: bool = False


def _now_ms() -> str:
    """Current time as HH:MM:SS.mmm string."""
    now = datetime.now(tz=UTC).astimezone()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def _caller_location() -> str:
    """Walk the call stack to find the first frame outside console.py itself.

    Return a short module path like 'services/push' or 'infra/oci'.
    Strip the 'src/margot/' prefix and '.py' suffix.
    Return 'margot' as fallback.
    """
    for frame_info in stack()[2:]:  # skip _caller_location + the console fn itself
        filename = frame_info.filename
        if "console.py" in filename:
            continue
        # Try to make relative to src/margot/
        try:
            rel = relpath(filename)
            # Strip leading src/margot/ and .py
            rel = rel.replace("\\", "/")
            for prefix in ("src/margot/", "margot/"):
                if prefix in rel:
                    rel = rel.split(prefix, 1)[1]
                    break
            return rel.removesuffix(".py")
        except ValueError:
            return "margot"
    return "margot"


def _get_stdout() -> Console:
    """Get or create stdout Console (uses current sys.stdout for test compatibility)."""
    # Always create fresh to use current sys.stdout (important for test runners)
    return Console(file=sys.stdout)


def _get_stderr() -> Console:
    """Get or create stderr Console (uses current sys.stderr for test compatibility)."""
    # Always create fresh to use current sys.stderr (important for test runners)
    return Console(file=sys.stderr)


def set_verbose(enabled: bool) -> None:
    """Enable or disable verbose output (step-level info)."""
    global _verbose  # noqa: PLW0603
    _verbose = enabled


def set_debug(enabled: bool) -> None:
    """Enable debug output (infra-level detail, implies verbose).

    When enabled=True: sets both _debug and _verbose to True.
    When enabled=False: sets _debug to False but does NOT reset _verbose.
    """
    global _debug, _verbose  # noqa: PLW0603
    _debug = enabled
    if enabled:
        _verbose = True


def is_verbose() -> bool:
    """Return True if verbose mode is active."""
    return _verbose


def is_debug() -> bool:
    """Return True if debug mode is active."""
    return _debug


def success(message: str) -> None:
    """Print a green success message to stdout. Always shown."""
    _get_stdout().print(f"[green]{message}[/green]")


def print_json(data: dict | list) -> None:
    """Pretty-print a JSON-serializable object to stdout. Always shown."""
    _get_stdout().print_json(dumps(data))


def warning(message: str) -> None:
    """Print a yellow warning to stderr. Always shown."""
    if _debug:
        _get_stderr().print(
            f"[dim]{_now_ms()}[/dim] [yellow]warning:[/yellow] [dim cyan][{_caller_location()}][/dim cyan] {message}"
        )
    else:
        _get_stderr().print(f"[yellow]warning:[/yellow] {message}")


def info(message: str) -> None:
    """Print a dim info message to stderr. Only shown if verbose=True."""
    if not _verbose:
        return
    if _debug:
        _get_stderr().print(f"[dim]{_now_ms()} info: [{_caller_location()}] {message}[/dim]")
    else:
        _get_stderr().print(f"[dim]info: {message}[/dim]")


def debug(message: str) -> None:
    """Print a debug message to stderr. Only shown if debug=True."""
    if not _debug:
        return
    _get_stderr().print(f"[dim]{_now_ms()} debug: [{_caller_location()}] {message}[/dim]")


def fatal(message: str) -> None:
    """Print a red error message to stderr and immediately exit with code 1.

    Use for unrecoverable errors in commands.
    """
    _get_stderr().print(f"[red]Error:[/red] {message}")
    raise Exit(1)
