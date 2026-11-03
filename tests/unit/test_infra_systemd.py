"""Unit tests for infra/systemd.py: systemctl --user argv, session check and daemon-reload, all with a mocked run."""

from pathlib import Path
import subprocess
from typing import Any

from pytest import fixture, mark, raises

from margot.infra import systemd


@fixture
def systemctl_path(mocker: Any) -> str:
    """Pretend systemctl lives at a fixed absolute path."""
    mocker.patch("margot.infra.systemd.which", return_value="/usr/bin/systemctl")
    return "/usr/bin/systemctl"


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestArgv:
    """Argument lists are built as lists, never shell strings."""

    def test_user_argv_uses_absolute_systemctl_and_user_flag(self, systemctl_path: str) -> None:
        """Should build [systemctl, --user, ...] with the absolute binary path."""
        assert systemd.user_argv("daemon-reload") == ["/usr/bin/systemctl", "--user", "daemon-reload"]

    def test_missing_systemctl_is_a_systemd_error(self, mocker: Any) -> None:
        """Should raise SystemdError when systemctl is not on PATH."""
        mocker.patch("margot.infra.systemd.which", return_value=None)

        with raises(systemd.SystemdError, match="systemctl"):
            systemd.user_argv("daemon-reload")


class TestSessionCheck:
    """Pre-check: the systemd user session must answer (sprint-13 §3.7)."""

    def test_usable_session_passes(self, mocker: Any, systemctl_path: str) -> None:
        """Should return without error when show-environment succeeds."""
        run = mocker.patch("margot.infra.systemd.run", return_value=_completed(0, "PATH=/usr/bin"))

        systemd.ensure_user_session()

        assert run.call_args.args[0] == ["/usr/bin/systemctl", "--user", "show-environment"]

    def test_unusable_session_names_the_user_session(self, mocker: Any, systemctl_path: str) -> None:
        """Should explain the user session and XDG_RUNTIME_DIR when the session is unreachable."""
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "", "Failed to connect to bus"))

        with raises(systemd.SystemdError, match=r"user session.*XDG_RUNTIME_DIR.*Failed to connect to bus"):
            systemd.ensure_user_session()

    def test_missing_binary_raises_systemd_error(self, mocker: Any) -> None:
        """Should map a missing binary to SystemdError, not a crash."""
        mocker.patch("margot.infra.systemd.which", return_value=None)

        with raises(systemd.SystemdError):
            systemd.ensure_user_session()


class TestDaemonReload:
    """Reload after placing files (sprint-13 §3.7)."""

    def test_daemon_reload_runs_the_user_command(self, mocker: Any, systemctl_path: str) -> None:
        """Should run systemctl --user daemon-reload exactly once."""
        run = mocker.patch("margot.infra.systemd.run", return_value=_completed(0))

        systemd.daemon_reload()

        run.assert_called_once()
        assert run.call_args.args[0] == ["/usr/bin/systemctl", "--user", "daemon-reload"]

    def test_failed_reload_trims_stderr_into_the_error(self, mocker: Any, systemctl_path: str) -> None:
        """Should include trimmed stderr in the SystemdError message."""
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "", "x" * 2000))

        with raises(systemd.SystemdError) as info:
            systemd.daemon_reload()

        assert "daemon-reload failed" in str(info.value)
        assert len(str(info.value)) < 1200


class TestRunWrapper:
    """The subprocess call itself: shell disabled, captured output, no check=True."""

    def test_run_calls_subprocess_without_shell_or_check(self, mocker: Any) -> None:
        """Should call subprocess.run with a list, shell=False and check=False."""
        popen = mocker.patch("margot.infra.systemd.subprocess.run", return_value=_completed(0))

        systemd.run(["/usr/bin/systemctl", "--user", "daemon-reload"])

        kwargs = popen.call_args.kwargs
        assert kwargs["shell"] is False
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True


class TestQuadletBinary:
    """The generator is looked up in the fixed podman paths first, then on PATH (sprint-13 §3.10, spike S1)."""

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
        """Should return the exit status and the raw stderr; the domain layer reads them (sprint-13 §3.10)."""
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


class TestUnitKnown:
    """`systemctl --user cat <service>` decides whether systemd knows a service (sprint-13 §3.10, guard 3)."""

    def test_known_service_exits_zero(self, mocker: Any, systemctl_path: str) -> None:
        """Should report a known service when cat exits 0."""
        run = mocker.patch("margot.infra.systemd.run", return_value=_completed(0, "# mosquitto.service"))

        assert systemd.unit_is_known("mosquitto.service") is True
        assert run.call_args.args[0] == ["/usr/bin/systemctl", "--user", "cat", "mosquitto.service"]

    def test_unknown_service_is_reported_not_raised(self, mocker: Any, systemctl_path: str) -> None:
        """Should report an unknown service as False when cat exits non-zero."""
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "", "No files found"))

        assert systemd.unit_is_known("missing.service") is False


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
