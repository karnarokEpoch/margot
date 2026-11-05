"""E2E tests for `margot install --no-reload` through the CLI (CliRunner).

The three public systemd functions are mocked and recorded. With the flag, none of them may be called.
Exit codes follow docs/exit-codes.md: 0 success, 1 unusable user session without the flag.
"""

from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

from pytest import fixture, mark
from typer.testing import CliRunner

from margot.infra.systemd import SystemdError
from margot.main import app
from tests.integration._install_helpers import build_project

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

pytestmark = mark.usefixtures("install_host")


def _plain_lines(text: str) -> list[str]:
    """Output lines with ANSI codes removed and surrounding spaces stripped."""
    return [_ANSI_RE.sub("", line).strip() for line in text.splitlines()]


@fixture
def systemd_calls(mocker: Any) -> SimpleNamespace:
    """The three public systemd functions, mocked and recorded. The session check succeeds unless a test changes it."""
    return SimpleNamespace(
        ensure=mocker.patch("margot.infra.systemd.ensure_user_session"),
        reload=mocker.patch("margot.infra.systemd.daemon_reload"),
        known=mocker.patch("margot.infra.systemd.unit_is_known", return_value=True),
    )


@fixture
def xdg(tmp_path: Path, monkeypatch: Any) -> Path:
    """Rootless Quadlet root under tmp_path, selected through XDG_CONFIG_HOME."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "containers" / "systemd"


def _project_args(tmp_path: Path) -> list[str]:
    project, build = build_project(tmp_path)
    return ["--project-dir", str(project), "--build-dir", str(build)]


class TestHelp:
    """The flag is documented in the command help."""

    def test_help_lists_no_reload_and_exits_0(self) -> None:
        """Should show --no-reload in the help output and exit 0."""
        result = runner.invoke(app, ["install", "--help"])

        assert result.exit_code == 0
        assert "--no-reload" in _ANSI_RE.sub("", result.output)


class TestNoReloadFlag:
    """--no-reload places the files and never contacts systemd."""

    def test_no_reload_yes_exits_0_and_prints_daemon_reload_and_start(
        self, tmp_path: Path, systemd_calls: SimpleNamespace, xdg: Path
    ) -> None:
        """Should exit 0, print the daemon-reload and start commands, and call none of the systemd functions."""
        result = runner.invoke(app, ["install", *_project_args(tmp_path), "--yes", "--no-reload"])

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "systemctl --user daemon-reload" in lines
        assert "systemctl --user start mosquitto.service" in lines
        assert (xdg / "com-belden-mosquitto" / "mosquitto.container").is_file()
        systemd_calls.ensure.assert_not_called()
        systemd_calls.reload.assert_not_called()
        systemd_calls.known.assert_not_called()

    def test_no_reload_says_systemd_was_not_contacted(self, tmp_path: Path, systemd_calls: SimpleNamespace, xdg: Path) -> None:
        """Should say in the next steps that systemd was not contacted."""
        result = runner.invoke(app, ["install", *_project_args(tmp_path), "--yes", "--no-reload"])

        assert result.exit_code == 0, result.output
        assert "systemd was not contacted (--no-reload)" in " ".join(_plain_lines(result.output))

    def test_without_flag_there_is_no_daemon_reload_line_and_exits_0(
        self, tmp_path: Path, systemd_calls: SimpleNamespace, xdg: Path
    ) -> None:
        """Should keep the usual next steps, with no daemon-reload line, and reload systemd once."""
        result = runner.invoke(app, ["install", *_project_args(tmp_path), "--yes"])

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "systemctl --user daemon-reload" not in lines
        assert "Next steps. install did not start anything; run these yourself:" in lines
        assert "systemctl --user start mosquitto.service" in lines
        systemd_calls.ensure.assert_called_once_with()
        systemd_calls.reload.assert_called_once_with()

    def test_no_reload_with_unreachable_session_exits_0_and_never_checks_it(
        self, tmp_path: Path, systemd_calls: SimpleNamespace, xdg: Path
    ) -> None:
        """Should not call the session check, so an unreachable user manager does not matter with the flag."""
        systemd_calls.ensure.side_effect = SystemdError("the user session is not reachable")

        result = runner.invoke(app, ["install", *_project_args(tmp_path), "--yes", "--no-reload"])

        assert result.exit_code == 0, result.output
        systemd_calls.ensure.assert_not_called()
        assert (xdg / "com-belden-mosquitto" / "mosquitto.container").is_file()


class TestDryRunWithNoReload:
    """--dry-run --no-reload behaves as --dry-run."""

    def test_dry_run_no_reload_exits_0_and_changes_nothing(
        self, tmp_path: Path, systemd_calls: SimpleNamespace, xdg: Path
    ) -> None:
        """Should exit 0, print the dry-run notice, write nothing and call no systemd function."""
        result = runner.invoke(app, ["install", *_project_args(tmp_path), "--dry-run", "--no-reload"])

        assert result.exit_code == 0, result.output
        assert "Dry run: nothing was changed on this host." in result.output
        assert not xdg.exists()
        systemd_calls.ensure.assert_not_called()
        systemd_calls.reload.assert_not_called()
        systemd_calls.known.assert_not_called()


class TestUnreachableSessionWithoutFlag:
    """Without --no-reload, an unusable user session still stops the install."""

    def test_unreachable_session_without_flag_exits_1_and_writes_nothing(
        self, tmp_path: Path, systemd_calls: SimpleNamespace, xdg: Path
    ) -> None:
        """Should exit 1 before any write when the systemd user session is not reachable."""
        systemd_calls.ensure.side_effect = SystemdError("the user session is not reachable")

        result = runner.invoke(app, ["install", *_project_args(tmp_path), "--yes"])

        assert result.exit_code == 1
        assert not xdg.exists()
        systemd_calls.reload.assert_not_called()
