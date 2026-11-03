"""Unit tests for infra/systemd.py: systemctl --user argv, session check and daemon-reload, all with a mocked run."""

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
