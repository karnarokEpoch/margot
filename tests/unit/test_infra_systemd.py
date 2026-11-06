"""Unit tests for infra/systemd.py: the user manager over D-Bus, the Quadlet generator and the run wrapper.

The D-Bus layer is replaced by a fake connection, so these tests never touch a real user manager. Socket
files are real (empty) files under tmp_path, because address resolution checks that the path exists.
"""

from pathlib import Path
import subprocess
from typing import Any

from jeepney import Message
from jeepney.low_level import HeaderFields
from pytest import fixture, mark, raises

from margot.infra import systemd
from margot.infra.dbus import DBusConnection, DBusError


class _FakeManager:
    """Stands in for DBusConnection. Answers the Manager and Unit calls systemd.py makes.

    ``known`` lists the unit names systemd has loaded. ``failing`` maps a call key to the DBusError it raises.
    Call keys are the method name, or ``Get:<property>`` for a Properties.Get call.
    """

    def __init__(self, *, known: frozenset[str] = frozenset(), failing: dict[str, DBusError] | None = None) -> None:
        self.known = known
        self.failing = failing or {}
        self.names: dict[str, str] = {}
        self.calls: list[str] = []
        self.timeouts: list[float] = []
        self.closed = False

    def call(self, message: Message, timeout: float) -> tuple[Any, ...]:
        member = str(message.header.fields.get(HeaderFields.member))
        key = f"Get:{message.body[1]}" if member == "Get" else member
        self.calls.append(key)
        self.timeouts.append(timeout)
        if key in self.failing:
            raise self.failing[key]
        if key == "Get:Environment":
            return (("as", ["PATH=/usr/bin"]),)
        if key == "Get:LoadState":
            name = self.names[str(message.header.fields.get(HeaderFields.path))]
            return (("s", "loaded" if name in self.known else "not-found"),)
        if key == "LoadUnit":
            name = str(message.body[0])
            path = "/org/freedesktop/systemd1/unit/" + name.replace(".", "_2e").replace("-", "_2d")
            self.names[path] = name
            return (path,)
        return ()

    def close(self) -> None:
        self.closed = True


@fixture
def runtime(tmp_path: Path, monkeypatch: Any) -> Path:
    """An XDG_RUNTIME_DIR under tmp_path and no session bus address, so the host environment cannot leak in."""
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(directory))
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    return directory


def _socket_file(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return str(path)


def _patch_connect(mocker: Any, manager: _FakeManager, refused: tuple[str, ...] = ()) -> list[tuple[str, bool]]:
    """Patch DBusConnection.connect. Returns the list that records each (path, hello) attempt, in order."""
    attempts: list[tuple[str, bool]] = []

    def connect(path: str, *, hello: bool, **_: float) -> _FakeManager:
        attempts.append((path, hello))
        if path in refused:
            raise DBusError(f"D-Bus authentication was refused by {path} (server answered: REJECTED EXTERNAL).")
        return manager

    mocker.patch.object(DBusConnection, "connect", side_effect=connect)
    return attempts


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestAddressOrder:
    """First candidate that connects wins: private socket, then the session bus from the environment, then bus."""

    def test_private_socket_is_tried_first_and_wins(self, mocker: Any, runtime: Path) -> None:
        """Should connect to <runtime>/systemd/private without Hello and stop there."""
        _socket_file(runtime / "systemd" / "private")
        _socket_file(runtime / "bus")
        attempts = _patch_connect(mocker, _FakeManager())

        systemd.ensure_user_session()

        assert attempts == [(str(runtime / "systemd" / "private"), False)]

    def test_session_bus_from_the_environment_comes_before_the_bus_socket(
        self, mocker: Any, runtime: Path, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """Should try the unix:path= of DBUS_SESSION_BUS_ADDRESS (with Hello) before <runtime>/bus."""
        session = _socket_file(tmp_path / "session" / "bus")
        _socket_file(runtime / "bus")
        _socket_file(runtime / "systemd" / "private")
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={session},guid=abc")
        attempts = _patch_connect(mocker, _FakeManager(), refused=(str(runtime / "systemd" / "private"),))

        systemd.ensure_user_session()

        assert attempts == [(str(runtime / "systemd" / "private"), False), (session, True)]

    def test_bus_socket_is_the_last_resort(self, mocker: Any, runtime: Path) -> None:
        """Should fall back to <runtime>/bus with Hello when the private socket is refused."""
        private = _socket_file(runtime / "systemd" / "private")
        bus = _socket_file(runtime / "bus")
        attempts = _patch_connect(mocker, _FakeManager(), refused=(private,))

        systemd.ensure_user_session()

        assert attempts == [(private, False), (bus, True)]

    def test_candidates_without_a_socket_file_are_skipped(self, mocker: Any, runtime: Path) -> None:
        """Should not try a path whose socket file does not exist."""
        bus = _socket_file(runtime / "bus")
        attempts = _patch_connect(mocker, _FakeManager())

        systemd.ensure_user_session()

        assert attempts == [(bus, True)]

    def test_abstract_session_address_is_skipped(self, mocker: Any, runtime: Path, monkeypatch: Any) -> None:
        """Should ignore unix:abstract= addresses: they never appear as a candidate."""
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:abstract=/tmp/dbus-abc,guid=1")
        bus = _socket_file(runtime / "bus")
        attempts = _patch_connect(mocker, _FakeManager())

        systemd.ensure_user_session()

        assert attempts == [(bus, True)]

    def test_session_address_with_several_entries_uses_the_unix_path_entry(
        self, mocker: Any, runtime: Path, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """Should split on ';' and take the entry that carries unix:path=, skipping the abstract one."""
        session = _socket_file(tmp_path / "s" / "bus")
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:abstract=/tmp/x;unix:path={session}")
        attempts = _patch_connect(mocker, _FakeManager())

        systemd.ensure_user_session()

        assert attempts == [(session, True)]

    def test_percent_encoded_session_path_is_decoded(self, mocker: Any, runtime: Path, monkeypatch: Any, tmp_path: Path) -> None:
        """Should decode %20 in the address path, as the D-Bus address syntax requires."""
        session = _socket_file(tmp_path / "a b" / "bus")
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/a%20b/bus")
        attempts = _patch_connect(mocker, _FakeManager())

        systemd.ensure_user_session()

        assert attempts == [(session, True)]

    def test_missing_xdg_runtime_dir_falls_back_to_run_user_uid(self, mocker: Any, runtime: Path, monkeypatch: Any) -> None:
        """Should use /run/user/<uid> as the runtime directory when XDG_RUNTIME_DIR is unset."""
        monkeypatch.delenv("XDG_RUNTIME_DIR")
        mocker.patch("margot.infra.systemd.os.getuid", return_value=4242)
        attempts = _patch_connect(mocker, _FakeManager())

        with raises(systemd.SystemdError, match=r"tried: /run/user/4242/systemd/private, /run/user/4242/bus\)"):
            systemd.ensure_user_session()

        assert attempts == []


class TestUnreachable:
    """When no candidate connects, the error names what was tried and the way out, including --no-reload."""

    def test_nothing_reachable_names_every_candidate_and_the_escape_hatch(self, mocker: Any, runtime: Path) -> None:
        """Should raise SystemdError that lists the candidates, names XDG_RUNTIME_DIR and mentions --no-reload."""
        attempts = _patch_connect(mocker, _FakeManager())

        with raises(systemd.SystemdError) as info:
            systemd.daemon_reload()

        message = str(info.value)
        assert attempts == []
        assert "The systemd user session is not reachable" in message
        assert str(runtime / "systemd" / "private") in message
        assert str(runtime / "bus") in message
        assert "XDG_RUNTIME_DIR" in message
        assert "--userns=keep-id" in message
        assert "--no-reload" in message

    def test_last_error_detail_is_appended(self, mocker: Any, runtime: Path) -> None:
        """Should append the last connection error, so the reason for a refusal is visible."""
        _socket_file(runtime / "systemd" / "private")
        _patch_connect(mocker, _FakeManager(), refused=(str(runtime / "systemd" / "private"),))

        with raises(systemd.SystemdError, match=r"REJECTED EXTERNAL.*"):
            systemd.ensure_user_session()

    def test_long_error_detail_is_trimmed(self, mocker: Any, runtime: Path) -> None:
        """Should trim a very long connection error with the shared _trim limit."""
        _socket_file(runtime / "systemd" / "private")

        def connect(*_args: Any, **_kwargs: Any) -> _FakeManager:
            raise DBusError("x" * 3000)

        mocker.patch.object(DBusConnection, "connect", side_effect=connect)

        with raises(systemd.SystemdError) as info:
            systemd.ensure_user_session()

        assert "x" * 601 not in str(info.value)
        assert str(info.value).endswith("...")


class TestEnsureUserSession:
    """The session check reads the Manager's Environment property."""

    def test_reachable_manager_passes(self, mocker: Any, runtime: Path) -> None:
        """Should read the Environment property and return without error."""
        _socket_file(runtime / "systemd" / "private")
        manager = _FakeManager()
        _patch_connect(mocker, manager)

        systemd.ensure_user_session()

        assert manager.calls == ["Get:Environment"]
        assert manager.closed is True

    def test_failed_environment_read_is_a_systemd_error_that_names_no_reload(self, mocker: Any, runtime: Path) -> None:
        """Should raise SystemdError with the --no-reload hint when the property read fails."""
        _socket_file(runtime / "systemd" / "private")
        _patch_connect(mocker, _FakeManager(failing={"Get:Environment": DBusError("org.freedesktop.DBus.Error.Timeout: slow")}))

        with raises(systemd.SystemdError, match=r"--no-reload.*Timeout: slow"):
            systemd.ensure_user_session()


class TestDaemonReload:
    """Reload after placing files: Manager.Reload() on the same connection rules."""

    def test_reload_is_called_once_with_the_reload_timeout(self, mocker: Any, runtime: Path) -> None:
        """Should call Manager.Reload exactly once, with the 120 second deadline."""
        _socket_file(runtime / "systemd" / "private")
        manager = _FakeManager()
        _patch_connect(mocker, manager)

        systemd.daemon_reload()

        assert manager.calls == ["Reload"]
        assert manager.timeouts == [120]
        assert manager.closed is True

    def test_failed_reload_keeps_the_error_name_in_the_message(self, mocker: Any, runtime: Path) -> None:
        """Should raise SystemdError that names daemon-reload and carries the D-Bus error."""
        _socket_file(runtime / "systemd" / "private")
        error = DBusError("org.freedesktop.systemd1.JobTimeoutReached: job timed out")
        _patch_connect(mocker, _FakeManager(failing={"Reload": error}))

        with raises(systemd.SystemdError) as info:
            systemd.daemon_reload()

        assert str(info.value) == "systemd daemon-reload failed: org.freedesktop.systemd1.JobTimeoutReached: job timed out"

    def test_unreachable_manager_is_a_systemd_error(self, mocker: Any, runtime: Path) -> None:
        """Should raise SystemdError, not a raw DBusError, when no candidate connects."""
        _patch_connect(mocker, _FakeManager())

        with raises(systemd.SystemdError, match="not reachable"):
            systemd.daemon_reload()


class TestUnitKnown:
    """Manager.LoadUnit then Unit.LoadState: a unit is known unless its LoadState is not-found."""

    def test_loaded_unit_is_known(self, mocker: Any, runtime: Path) -> None:
        """Should report True for a unit whose LoadState is loaded."""
        _socket_file(runtime / "systemd" / "private")
        manager = _FakeManager(known=frozenset({"podman.socket"}))
        _patch_connect(mocker, manager)

        assert systemd.unit_is_known("podman.socket") is True
        assert manager.calls == ["LoadUnit", "Get:LoadState"]

    def test_not_found_unit_is_unknown(self, mocker: Any, runtime: Path) -> None:
        """Should report False, not raise, for a unit whose LoadState is not-found."""
        _socket_file(runtime / "systemd" / "private")
        _patch_connect(mocker, _FakeManager())

        assert systemd.unit_is_known("margot-nonexistent.service") is False

    def test_dbus_failure_while_reading_the_state_is_a_systemd_error(self, mocker: Any, runtime: Path) -> None:
        """Should raise SystemdError that names the service when the LoadState read fails."""
        _socket_file(runtime / "systemd" / "private")
        error = DBusError("org.freedesktop.DBus.Error.AccessDenied: denied")
        _patch_connect(mocker, _FakeManager(failing={"Get:LoadState": error}))

        with raises(systemd.SystemdError, match=r"mosquitto\.service.*AccessDenied"):
            systemd.unit_is_known("mosquitto.service")

    def test_unreachable_manager_is_a_systemd_error(self, mocker: Any, runtime: Path) -> None:
        """Should raise SystemdError when the user manager cannot be reached."""
        _patch_connect(mocker, _FakeManager())

        with raises(systemd.SystemdError, match="--no-reload"):
            systemd.unit_is_known("mosquitto.service")


class TestRunWrapper:
    """The subprocess call itself: shell disabled, captured output, no check=True."""

    def test_run_calls_subprocess_without_shell_or_check(self, mocker: Any) -> None:
        """Should call subprocess.run with a list, shell=False and check=False."""
        popen = mocker.patch("margot.infra.systemd.subprocess.run", return_value=_completed(0))

        systemd.run(["/usr/libexec/podman/quadlet", "-dryrun", "-user"])

        kwargs = popen.call_args.kwargs
        assert kwargs["shell"] is False
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True


class TestQuadletBinary:
    """The generator is looked up in the fixed podman paths first, then on PATH."""

    def test_libexec_path_wins_when_executable(self, mocker: Any) -> None:
        """Should return /usr/libexec/podman/quadlet when it is an executable file."""
        mocker.patch("margot.infra.systemd.Path.is_file", return_value=True)
        mocker.patch("margot.infra.systemd.os.access", return_value=True)

        assert systemd.quadlet_binary() == "/usr/libexec/podman/quadlet"

    def test_lib_path_is_the_second_choice(self, mocker: Any) -> None:
        """Should use /usr/lib/podman/quadlet when the libexec path is absent."""
        mocker.patch(
            "margot.infra.systemd.os.access",
            side_effect=lambda path, _mode: path == "/usr/lib/podman/quadlet",
        )
        mocker.patch(
            "margot.infra.systemd.Path.is_file",
            autospec=True,
            side_effect=lambda self: str(self) == "/usr/lib/podman/quadlet",
        )

        assert systemd.quadlet_binary() == "/usr/lib/podman/quadlet"

    def test_path_lookup_is_the_last_choice(self, mocker: Any) -> None:
        """Should fall back to a quadlet found on PATH."""
        mocker.patch("margot.infra.systemd.Path.is_file", return_value=False)
        mocker.patch("margot.infra.systemd.which", return_value="/opt/bin/quadlet")

        assert systemd.quadlet_binary() == "/opt/bin/quadlet"

    def test_no_binary_gives_none(self, mocker: Any) -> None:
        """Should return None when no generator exists anywhere."""
        mocker.patch("margot.infra.systemd.Path.is_file", return_value=False)
        mocker.patch("margot.infra.systemd.which", return_value=None)

        assert systemd.quadlet_binary() is None


ENVIRON = {"PATH": "/usr/bin:/bin", "HOME": "/home/u", "XDG_RUNTIME_DIR": "/run/user/1000", "KEEP": "yes"}


class TestGeneratorRun:
    """`quadlet -dryrun -user` with QUADLET_UNIT_DIRS pointing at the staged tree; nothing is written."""

    def test_exit_status_and_stderr_are_returned_unchanged(self, mocker: Any, tmp_path: Path) -> None:
        """Should return the exit status and the raw stderr; the domain layer reads them."""
        stderr = 'quadlet-generator[1]: converting "web.container": requested Quadlet unit x.network was not found'
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "", stderr))

        run = systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        assert run == systemd.GeneratorRun(returncode=1, stderr=stderr)

    def test_zero_exit_with_progress_lines_is_returned_as_is(self, mocker: Any, tmp_path: Path) -> None:
        """Should return exit 0 and the 'Loading source' progress lines, which quadlet logs for every valid tree."""
        progress = "quadlet-generator[1]: Loading source unit file /x/verify-mqtt.container"
        mocker.patch("margot.infra.systemd.run", return_value=_completed(0, "", progress))

        run = systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        assert run.returncode == 0
        assert run.stderr == progress

    def test_generator_stdout_is_not_kept(self, mocker: Any, tmp_path: Path) -> None:
        """Should drop the generated service blocks on stdout: they are not needed to judge the tree."""
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "---SECRET=1---", "bad unit"))

        run = systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        assert "SECRET" not in repr(run)

    def test_argv_is_the_dry_run_user_command_and_environment_keeps_the_user_env(self, mocker: Any, tmp_path: Path) -> None:
        """Should run `<binary> -dryrun -user` with the user's environment plus QUADLET_UNIT_DIRS only."""
        run = mocker.patch("margot.infra.systemd.run", return_value=_completed(0))

        systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        argv = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        assert argv == ["/usr/libexec/podman/quadlet", "-dryrun", "-user"]
        assert env["QUADLET_UNIT_DIRS"] == str(tmp_path)
        assert env["PATH"] == "/usr/bin:/bin"
        assert env["HOME"] == "/home/u"
        assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
        assert env["KEEP"] == "yes"

    def test_caller_environment_is_not_mutated(self, mocker: Any, tmp_path: Path) -> None:
        """Should build a new environment mapping, leaving the caller's mapping untouched."""
        mocker.patch("margot.infra.systemd.run", return_value=_completed(0))
        environ = dict(ENVIRON)

        systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", environ)

        assert "QUADLET_UNIT_DIRS" not in environ

    def test_without_a_unit_dir_the_real_search_path_is_used(self, mocker: Any) -> None:
        """Should run the dry run with the default search path: no QUADLET_UNIT_DIRS, even if the caller has one."""
        run = mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "", "bad unit"))

        result = systemd.check_units(None, "/usr/libexec/podman/quadlet", {**ENVIRON, "QUADLET_UNIT_DIRS": "/stale"})

        assert run.call_args.args[0] == ["/usr/libexec/podman/quadlet", "-dryrun", "-user"]
        env = run.call_args.kwargs["env"]
        assert "QUADLET_UNIT_DIRS" not in env
        assert env["PATH"] == "/usr/bin:/bin"
        assert result == systemd.GeneratorRun(returncode=1, stderr="bad unit")

    @mark.parametrize("error", [OSError("Exec format error"), subprocess.TimeoutExpired(cmd="quadlet", timeout=120)])
    def test_a_generator_that_cannot_run_is_a_systemd_error(self, mocker: Any, tmp_path: Path, error: Exception) -> None:
        """Should raise SystemdError, not the raw OS or timeout error, so the caller can exit with the install message."""
        mocker.patch("margot.infra.systemd.run", side_effect=error)

        with raises(systemd.SystemdError, match=r"could not run the Quadlet generator"):
            systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)


class TestRunEnvironment:
    """The run wrapper passes an explicit environment only when one is given."""

    def test_run_passes_env_when_given(self, mocker: Any) -> None:
        """Should forward the env mapping to subprocess.run."""
        popen = mocker.patch("margot.infra.systemd.subprocess.run", return_value=_completed(0))

        systemd.run(["/bin/true"], env={"A": "1"})

        assert popen.call_args.kwargs["env"] == {"A": "1"}

    def test_run_inherits_the_environment_by_default(self, mocker: Any) -> None:
        """Should leave env unset (inherit) when none is given."""
        popen = mocker.patch("margot.infra.systemd.subprocess.run", return_value=_completed(0))

        systemd.run(["/bin/true"])

        assert popen.call_args.kwargs.get("env") is None
