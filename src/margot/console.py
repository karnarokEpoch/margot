"""Central output hub for margot CLI.

All terminal output goes through this module. Provides consistent formatting
and routing (stdout vs stderr) for success, warnings, info, debug, and fatal messages.

Verbosity is controlled by two module-level flags:
  - _verbose: Enables info() output (high-level step logs).
  - _debug: Enables debug() output (low-level infra calls). Implies _verbose.
"""

import sys

from rich.console import Console
from typer import Exit

_stdout = Console(file=sys.stdout)
_stderr = Console(file=sys.stderr)
_verbose: bool = False
_debug: bool = False


def set_verbose(enabled: bool) -> None:
    """Enable or disable verbose output (step-level info)."""
    global _verbose
    _verbose = enabled


def set_debug(enabled: bool) -> None:
    """Enable debug output (infra-level detail, implies verbose).
    
    When enabled=True: sets both _debug and _verbose to True.
    When enabled=False: sets _debug to False but does NOT reset _verbose.
    """
    global _debug, _verbose
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
    _stdout.print(f"[green]{message}[/green]")


def warning(message: str) -> None:
    """Print a yellow warning message to stderr. Always shown."""
    _stderr.print(f"[yellow]Warning:[/yellow] {message}")


def info(message: str) -> None:
    """Print a dim step-level info message to stderr. Only shown if verbose=True."""
    if _verbose:
        _stderr.print(f"[dim]{message}[/dim]")


def debug(message: str) -> None:
    """Print a dim cyan debug message to stderr. Only shown if debug=True."""
    if _debug:
        _stderr.print(f"[dim cyan]debug:[/dim cyan] [dim]{message}[/dim]")


def fatal(message: str) -> None:
    """Print a red error message to stderr and immediately exit with code 1.
    
    Use for unrecoverable errors in commands.
    """
    _stderr.print(f"[red]Error:[/red] {message}")
    raise Exit(1)
