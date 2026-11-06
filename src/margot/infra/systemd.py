"""systemd user manager and Quadlet generator wrapper for `margot install`.

The user manager is queried over its D-Bus socket (see ``infra/dbus.py``), so no ``systemctl`` binary is needed.
The first reachable candidate wins: the private socket of the user manager, then the session bus named by
``DBUS_SESSION_BUS_ADDRESS``, then ``<runtime>/bus``. The Quadlet generator is a local binary. It runs in dry-run
mode, so it never writes to the host. Every subprocess call is an argument list with shell disabled, captured
text output and no ``check=True``.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
from shutil import which
import subprocess
from urllib.parse import unquote

from jeepney import DBusAddress, Properties, new_method_call

from margot import console
from margot.infra.dbus import DBusConnection, DBusError

_TIMEOUT_SECONDS = 120
_CONNECT_SECONDS = 10
_MAX_DETAIL_CHARS = 600
# Fixed locations first; Podman 5.8.2 ships the generator under libexec only.
QUADLET_BINARIES = ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet")
_BUS_NAME = "org.freedesktop.systemd1"
_MANAGER = DBusAddress("/org/freedesktop/systemd1", bus_name=_BUS_NAME, interface="org.freedesktop.systemd1.Manager")
_UNIT_INTERFACE = "org.freedesktop.systemd1.Unit"


class SystemdError(Exception):
    """The systemd user manager is unreachable or refused a call, or the Quadlet generator cannot run."""


@dataclass(frozen=True)
class GeneratorRun:
    """Exit status and stderr of a Quadlet generator dry-run. The generated services on stdout are not kept.

    The domain layer decides what the stderr means (``domain.install.judge_generator``).
    """

    returncode: int
    stderr: str


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


def _runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def _session_bus_paths() -> list[str]:
    """The ``unix:path=`` entries of DBUS_SESSION_BUS_ADDRESS, in order. Abstract and other transports are skipped."""
    paths: list[str] = []
    for address in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "").split(";"):
        transport, _, params = address.partition(":")
        if transport != "unix":
            continue
        for param in params.split(","):
            key, _, value = param.partition("=")
            if key == "path" and value:
                paths.append(unquote(value))
    return paths


def _candidates() -> list[tuple[str, bool]]:
    """Socket paths in the order they are tried, each with whether Hello() must be sent (session bus only)."""
    runtime = _runtime_dir()
    ordered = [(str(runtime / "systemd" / "private"), False)]
    ordered += [(path, True) for path in _session_bus_paths()]
    ordered.append((str(runtime / "bus"), True))
    unique: dict[str, bool] = {}
    for path, hello in ordered:
        unique.setdefault(path, hello)
    return list(unique.items())


def _unreachable(detail: DBusError | None) -> SystemdError:
    """The one message for an unreachable user session: what was tried, the usual causes, and the way out."""
    tried = ", ".join(path for path, _ in _candidates())
    message = (
        f"The systemd user session is not reachable (tried: {tried}). Check that XDG_RUNTIME_DIR is set and the "
        "user manager is running; in a container, mount the socket and run with --userns=keep-id. "
        "To only place the files, pass --no-reload."
    )
    if detail is not None:
        message = f"{message} {_trim(str(detail))}"
    return SystemdError(message)


def _open_manager() -> DBusConnection:
    """Connect to the first candidate that exists and accepts the connection.

    Raises:
        SystemdError: No candidate connects. The message lists the candidates and the last error.
    """
    last_error: DBusError | None = None
    for path, hello in _candidates():
        if not Path(path).exists():
            continue
        try:
            return DBusConnection.connect(path, hello=hello, timeout=_CONNECT_SECONDS)
        except DBusError as error:
            last_error = error
    raise _unreachable(last_error)


@contextmanager
def _manager() -> Iterator[DBusConnection]:
    """An open connection to the user manager, closed on exit."""
    connection = _open_manager()
    try:
        yield connection
    finally:
        connection.close()


def ensure_user_session() -> None:
    """Check that the systemd user manager answers, by reading its Environment property.

    Raises:
        SystemdError: The user manager is unreachable or the property read fails.
    """
    try:
        with _manager() as connection:
            connection.call(Properties(_MANAGER).get("Environment"), timeout=_TIMEOUT_SECONDS)
    except DBusError as error:
        raise _unreachable(error) from error
    console.info("systemd user session is usable.")


def daemon_reload() -> None:
    """Reload the user manager so it regenerates units from the Quadlet directories.

    Raises:
        SystemdError: The user manager is unreachable or Manager.Reload() returns an error.
    """
    with _manager() as connection:
        try:
            connection.call(new_method_call(_MANAGER, "Reload"), timeout=_TIMEOUT_SECONDS)
        except DBusError as error:
            raise SystemdError(f"systemd daemon-reload failed: {_trim(str(error))}") from error
    console.info("systemd user manager reloaded.")


def unit_is_known(service: str) -> bool:
    """True when systemd knows the unit: its LoadState is anything but ``not-found``.

    Raises:
        SystemdError: The user manager is unreachable or a call on it fails.
    """
    with _manager() as connection:
        try:
            (unit_path,) = connection.call(new_method_call(_MANAGER, "LoadUnit", "s", (service,)), timeout=_TIMEOUT_SECONDS)
            unit = DBusAddress(unit_path, bus_name=_BUS_NAME, interface=_UNIT_INTERFACE)
            ((_, state),) = connection.call(Properties(unit).get("LoadState"), timeout=_TIMEOUT_SECONDS)
        except DBusError as error:
            raise SystemdError(f"could not read the state of {service} from systemd: {_trim(str(error))}") from error
    return state != "not-found"


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


def check_units(unit_dir: Path | None, binary: str, environ: Mapping[str, str]) -> GeneratorRun:
    """Run `<binary> -dryrun -user` and return its exit status and stderr.

    With ``unit_dir``, ``QUADLET_UNIT_DIRS`` replaces the search path, so the dry run sees only the staged
    tree (guard 2). With None, the variable is removed and the generator scans the real Quadlet search path
    (guard 3). The generated services on stdout are not kept; the domain layer judges the stderr.

    Raises:
        SystemdError: If the generator cannot be started or does not finish in time.
    """
    env = {key: value for key, value in environ.items() if key != "QUADLET_UNIT_DIRS"}
    if unit_dir is not None:
        env["QUADLET_UNIT_DIRS"] = str(unit_dir)
    try:
        result = run([binary, "-dryrun", "-user"], env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SystemdError(f"margot could not run the Quadlet generator ({binary}): {error}") from error
    console.debug(f"Quadlet generator dry run exited with status {result.returncode}.")
    return GeneratorRun(returncode=result.returncode, stderr=result.stderr)
