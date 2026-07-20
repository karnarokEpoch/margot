"""Version command: print margot version."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed margot package version, or 'unknown' if not installed."""
    try:
        return version("margot")
    except PackageNotFoundError:
        return "unknown"
