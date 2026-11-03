"""Unit tests for infra/systemd.py: systemctl --user argv, session check and daemon-reload, all with a mocked run."""

from pathlib import Path
import subprocess
from typing import Any

from pytest import fixture, raises

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


class TestGeneratorCheck:
    """`quadlet -dryrun -user` with QUADLET_UNIT_DIRS pointing at the staged tree; nothing is written."""


    def test_valid_tree_passes(self, mocker: Any, tmp_path: Path) -> None:
        """Should pass when the generator exits 0 with no error output."""
        mocker.patch("margot.infra.systemd.run", return_value=_completed(0, "---web.service---\n[Service]\n"))

        check = systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        assert check.passed is True
        assert check.detail == ""

    def test_invalid_tree_fails_with_the_generator_message(self, mocker: Any, tmp_path: Path) -> None:
        """Should fail and carry the generator's error text when it exits non-zero."""
        mocker.patch(
            "margot.infra.systemd.run",
            return_value=_completed(1, "", "web.container: unknown key 'Imag'\nprocessing encountered some errors"),
        )

        check = systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        assert check.passed is False
        assert "unknown key 'Imag'" in check.detail

    def test_generator_stdout_is_never_part_of_the_detail(self, mocker: Any, tmp_path: Path) -> None:
        """Should keep the generated service blocks out of the message (they are not an error)."""
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "---SECRET=1---", "bad unit"))

        check = systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        assert "SECRET" not in check.detail

    def test_zero_exit_passes_even_when_quadlet_logs_progress_on_stderr(self, mocker: Any, tmp_path: Path) -> None:
        """Should pass on exit 0: quadlet logs 'Loading source ...' lines on stderr for every valid tree (host check)."""
        progress = "quadlet-generator[1]: Loading source unit file /x/verify-mqtt.container"
        mocker.patch("margot.infra.systemd.run", return_value=_completed(0, "", progress))

        check = systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        assert check.passed is True

    def test_failure_detail_leaves_out_the_progress_lines(self, mocker: Any, tmp_path: Path) -> None:
        """Should keep only the error lines of a failed run, not the 'Loading source' progress lines."""
        stderr = (
            "quadlet-generator[1]: Loading source unit file /x/verify-bad.container\n"
            "quadlet-generator[1]: converting \"verify-bad.container\": unsupported key 'NoSuchKey'\n"
            "quadlet-generator[1]: processing encountered some errors"
        )
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "", stderr))

        check = systemd.check_units(tmp_path, "/usr/libexec/podman/quadlet", ENVIRON)

        assert check.passed is False
        assert "unsupported key 'NoSuchKey'" in check.detail
        assert "Loading source" not in check.detail

    def test_argv_is_the_dry_run_user_command_and_environment_keeps_the_user_env(
        self, mocker: Any, tmp_path: Path
    ) -> None:
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
