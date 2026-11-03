"""systemctl --user and Quadlet generator wrapper for `margot install`.

Every call is an argument list with shell disabled, captured text output and no ``check=True``.
The binary is resolved with ``shutil.which`` so the list starts with an absolute path. The generator
runs in dry-run mode, so it never writes to the host.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
from shutil import which
import subprocess

from margot import console

_TIMEOUT_SECONDS = 120
_MAX_DETAIL_CHARS = 600
# Fixed locations first; Podman 5.8.2 ships the generator under libexec only (sprint-13 spike S1).
QUADLET_BINARIES = ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet")


class SystemdError(Exception):
    """A systemctl --user call failed or the user session is not usable."""


@dataclass(frozen=True)
class GeneratorCheck:
    """Outcome of a Quadlet generator dry-run. ``detail`` is the trimmed error text when it failed."""

    passed: bool
    detail: str


def user_argv(*args: str) -> list[str]:
    """Build ``[<absolute systemctl>, "--user", *args]``.

    Raises:
        SystemdError: If systemctl is not on PATH.
    """
    binary = which("systemctl")
    if binary is None:
        raise SystemdError("systemctl was not found on PATH. margot install needs a systemd user session.")
    return [binary, "--user", *args]


def run(argv: list[str], env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run an argument list and capture its text output. Never shell, never raises on exit status.

    ``env`` replaces the process environment when given; by default the process inherits it.
    """
    console.debug(f"exec: {' '.join(argv)}")
    return subprocess.run(  # noqa: S603 - argv is a list built by margot, shell is disabled
        argv,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=_TIMEOUT_SECONDS,
        env=None if env is None else dict(env),
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


def quadlet_binary() -> str | None:
    """Return the Quadlet generator: the fixed podman locations first, then PATH. None when absent."""
    for candidate in QUADLET_BINARIES:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return which("quadlet")


def check_units(unit_dir: Path, binary: str, environ: Mapping[str, str]) -> GeneratorCheck:
    """Run `<binary> -dryrun -user` with ``QUADLET_UNIT_DIRS`` pointing at the staged tree (sprint-13 §3.10).

    The generator replaces the default search path with ``unit_dir``. Its generated services stay on
    stdout and are not shown. The environment is the caller's, plus ``QUADLET_UNIT_DIRS``.
    A non-zero exit or any error output fails the check; the detail is the trimmed error text.
    """
    result = run([binary, "-dryrun", "-user"], env={**environ, "QUADLET_UNIT_DIRS": str(unit_dir)})
    if result.returncode == 0 and not result.stderr.strip():
        console.debug("Quadlet generator accepted the staged units.")
        return GeneratorCheck(passed=True, detail="")
    detail = _trim(result.stderr) or f"generator exited with status {result.returncode}"
    return GeneratorCheck(passed=False, detail=detail)


def unit_is_known(service: str) -> bool:
    """True when systemd knows the unit: `systemctl --user cat <service>` exits 0 (sprint-13 §3.10, guard 3).

    Raises:
        SystemdError: If systemctl is not available.
    """
    return run(user_argv("cat", service)).returncode == 0
