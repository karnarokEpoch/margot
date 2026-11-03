"""systemctl --user wrapper for `margot install`.

Every call is an argument list with shell disabled, captured text output and no ``check=True``.
The binary is resolved with ``shutil.which`` so the list starts with an absolute path.
"""

from shutil import which
import subprocess

from margot import console

_TIMEOUT_SECONDS = 120
_MAX_DETAIL_CHARS = 600


class SystemdError(Exception):
    """A systemctl --user call failed or the user session is not usable."""


def user_argv(*args: str) -> list[str]:
    """Build ``[<absolute systemctl>, "--user", *args]``.

    Raises:
        SystemdError: If systemctl is not on PATH.
    """
    binary = which("systemctl")
    if binary is None:
        raise SystemdError("systemctl was not found on PATH. margot install needs a systemd user session.")
    return [binary, "--user", *args]


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run an argument list and capture its text output. Never shell, never raises on exit status."""
    console.debug(f"exec: {' '.join(argv)}")
    return subprocess.run(  # noqa: S603 - argv is a list built by margot, shell is disabled
        argv,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=_TIMEOUT_SECONDS,
    )


def ensure_user_session() -> None:
    """Check that the systemd user session answers (sprint-13 §3.7, pre-check 1).

    Raises:
        SystemdError: If `systemctl --user show-environment` fails.
    """
    result = run(user_argv("show-environment"))
    if result.returncode != 0:
        detail = _trim(result.stderr)
        raise SystemdError(
            "The systemd user session is not usable. Check that XDG_RUNTIME_DIR is set and that the "
            f"session is running. {detail}".rstrip()
        )
    console.info("systemd user session is usable.")


def daemon_reload() -> None:
    """Reload the user manager so it regenerates units from the Quadlet directories.

    Raises:
        SystemdError: If `systemctl --user daemon-reload` exits non-zero.
    """
    result = run(user_argv("daemon-reload"))
    if result.returncode != 0:
        raise SystemdError(f"systemctl --user daemon-reload failed: {_trim(result.stderr)}")
    console.info("systemd user manager reloaded.")


def _trim(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= _MAX_DETAIL_CHARS:
        return cleaned
    return cleaned[:_MAX_DETAIL_CHARS] + "..."
