"""E2E tests for `margot install` through the CLI (CliRunner), with the systemd user manager and the registry mocked.

Exit codes follow the taxonomy in docs/exit-codes.md: 2 usage, 3 validation, 4 registry, 1 host/declined.
"""

import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

from pytest import fixture, mark
from typer.testing import CliRunner

from margot.domain.install import MARKER_FILENAME
from margot.domain.models import PackageType
from margot.infra.credentials import CredentialsExpiredError
from margot.infra.systemd import GeneratorRun, SystemdError
from margot.main import app
from tests.integration._install_helpers import (
    REPOSITORY,
    answer_by_run,
    app_description,
    build_project,
    build_static_folder,
    quadlet_payload,
    write_tar,
)

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

pytestmark = mark.usefixtures("install_host")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


def _systemd_calls(manager: Any) -> list[str]:
    """The systemd functions called, in order. A service check is written as ``unit_is_known:<service>``."""
    return [f"unit_is_known:{call.args[0]}" if call[0] == "unit_is_known" else call[0] for call in manager.mock_calls]


@fixture
def systemctl(mocker: Any) -> Any:
    """The systemd user manager answers every call. The three systemd functions are children of one mock.

    The order of calls is read with ``_systemd_calls``; an empty ``mock_calls`` means systemd was never contacted.
    """
    manager = mocker.Mock()
    manager.unit_is_known.return_value = True
    mocker.patch("margot.infra.systemd.ensure_user_session", manager.ensure_user_session)
    mocker.patch("margot.infra.systemd.daemon_reload", manager.daemon_reload)
    mocker.patch("margot.infra.systemd.unit_is_known", manager.unit_is_known)
    return manager


@fixture
def xdg(tmp_path: Path, monkeypatch: Any) -> Path:
    """Rootless Quadlet root under tmp_path, selected through XDG_CONFIG_HOME."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "containers" / "systemd"


@fixture
def staging_tmp(tmp_path: Path, monkeypatch: Any) -> Path:
    """Temporary directory used for staging, so leftovers can be counted."""
    directory = tmp_path / "staging-tmp"
    directory.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(directory))
    return directory


def _leftovers(staging: Path) -> list[str]:
    return [p.name for p in staging.iterdir() if p.name.startswith("margot-install-")]


def _project_args(tmp_path: Path) -> tuple[list[str], Path]:
    project, build = build_project(tmp_path)
    return ["--project-dir", str(project), "--build-dir", str(build)], build


class TestHelp:
    """The command exists and documents its options."""

    def test_help_lists_the_options_including_set(self) -> None:
        """Should show --dry-run, --yes, --profile and the repeatable --set."""
        result = runner.invoke(app, ["install", "--help"])

        assert result.exit_code == 0
        plain = _strip_ansi(result.output)
        assert "--dry-run" in plain
        assert "--yes" in plain
        assert "--profile" in plain
        assert "--set" in plain


class TestUsageErrors:
    """Usage errors are exit 2 and happen before any work."""

    def test_uri_with_project_dir_exits_2(self, tmp_path: Path, systemctl: Any) -> None:
        """Should exit 2 when a URI and --project-dir are both given."""
        result = runner.invoke(app, ["install", f"{REPOSITORY}:1.0.2", "--project-dir", str(tmp_path), "--yes"])

        assert result.exit_code == 2

    def test_build_dir_outside_project_mode_exits_2(self, tmp_path: Path, systemctl: Any) -> None:
        """Should exit 2 when --build-dir is given for a static folder."""
        folder = build_static_folder(tmp_path)

        result = runner.invoke(app, ["install", "--project-dir", str(folder), "--build-dir", str(tmp_path), "--yes"])

        assert result.exit_code == 2

    def test_no_terminal_without_yes_or_dry_run_exits_2(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 2 without asking when stdin is not a terminal and --yes is missing."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args])

        assert result.exit_code == 2
        assert not xdg.exists()


class TestExitCodesOfValidation:
    """Exit code 3: descriptor, profile and component problems."""

    def test_no_descriptor_exits_3(self, tmp_path: Path, systemctl: Any) -> None:
        """Should exit 3 when the directory has no descriptor at all."""
        empty = tmp_path / "empty"
        empty.mkdir()

        result = runner.invoke(app, ["install", "--project-dir", str(empty), "--yes"])

        assert result.exit_code == 3

    def test_unknown_profile_exits_3(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 3 for an unknown --profile id."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--profile", "nope", "--yes"])

        assert result.exit_code == 3
        assert "No deployment profile with id 'nope'" in result.output

    def test_compose_profile_exits_3_with_not_supported_message(self, tmp_path: Path, systemctl: Any) -> None:
        """Should exit 3 with the 'not supported yet' message for a compose profile."""
        folder = build_static_folder(
            tmp_path,
            descriptor=app_description(profile_type="compose", profile_id="compose-v1"),
        )

        result = runner.invoke(app, ["install", "--project-dir", str(folder), "--profile", "compose-v1", "--yes"])

        assert result.exit_code == 3
        assert "not supported yet" in result.output

    def test_ownership_refusal_exits_3_and_writes_nothing(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 3 for an application directory that margot did not create."""
        args, _ = _project_args(tmp_path)
        (xdg / "com-belden-mosquitto").mkdir(parents=True)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 3
        assert "not installed by margot" in result.output
        assert sorted(p.name for p in (xdg / "com-belden-mosquitto").iterdir()) == []


class TestExitCodesOfRegistryAndHost:
    """Exit code 4 for registry problems, 1 for host problems and declines."""

    def test_expired_credentials_exit_4(self, tmp_path: Path, mocker: Any, systemctl: Any, staging_tmp: Path) -> None:
        """Should exit 4 and leave no staging directory when credentials have expired."""
        remote_app = tmp_path / "remote-app.yaml"
        remote_app.write_text(app_description(), encoding="utf-8")
        mocker.patch(
            "margot.services.remote.resolve_remote_descriptor",
            return_value=SimpleNamespace(
                normalized_uri=f"{REPOSITORY}:1.0.3",
                app_yaml_path=str(remote_app),
                temp_dir=SimpleNamespace(cleanup=lambda: None),
            ),
        )
        mocker.patch("margot.services.pull.prepare_oci_retrieval", side_effect=CredentialsExpiredError("expired"))

        result = runner.invoke(app, ["install", f"{REPOSITORY}:1.0.3", "--yes"])

        assert result.exit_code == 4
        assert _leftovers(staging_tmp) == []

    def test_unusable_user_session_exits_1(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 1 and name the user session when the systemd user manager cannot be reached."""
        systemctl.ensure_user_session.side_effect = SystemdError(
            "The systemd user session is not reachable (tried: /run/user/1000/bus). --no-reload"
        )
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 1
        assert "user session" in result.output
        assert "--no-reload" in result.output
        assert not xdg.exists()

    def test_declined_confirmation_exits_1_and_writes_nothing(
        self, tmp_path: Path, mocker: Any, systemctl: Any, xdg: Path
    ) -> None:
        """Should exit 1 with 'Aborted' when the user answers no."""
        mocker.patch("margot.console.is_interactive", return_value=True)
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args], input="n\n")

        assert result.exit_code == 1
        assert "Aborted: nothing was installed" in result.output
        assert not xdg.exists()


class TestDryRun:
    """--dry-run prints the plan and changes nothing, and never asks."""

    def test_dry_run_exits_0_and_leaves_host_untouched(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 0, print the plan, and call neither systemctl nor create the Quadlet root."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0
        assert "mosquitto.service" in result.output
        assert not xdg.exists()
        assert systemctl.mock_calls == []

    def test_dry_run_never_asks_even_on_a_terminal(self, tmp_path: Path, mocker: Any, systemctl: Any) -> None:
        """Should not call confirm on a terminal when --dry-run is given."""
        mocker.patch("margot.console.is_interactive", return_value=True)
        confirm = mocker.patch("margot.console.confirm")
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0
        confirm.assert_not_called()

    def test_dry_run_of_static_folder(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should show the plan for a static folder without writing."""
        folder = build_static_folder(tmp_path)

        result = runner.invoke(app, ["install", "--project-dir", str(folder), "--dry-run"])

        assert result.exit_code == 0
        assert "static" in result.output
        assert not xdg.exists()

    def test_dry_run_of_remote_artifact(self, tmp_path: Path, mocker: Any, systemctl: Any, xdg: Path) -> None:
        """Should show the plan for a remote artifact without writing."""
        remote_app = tmp_path / "remote-app.yaml"
        remote_app.write_text(app_description(), encoding="utf-8")
        mocker.patch(
            "margot.services.remote.resolve_remote_descriptor",
            return_value=SimpleNamespace(
                normalized_uri=f"{REPOSITORY}:1.0.3",
                app_yaml_path=str(remote_app),
                temp_dir=SimpleNamespace(cleanup=lambda: None),
            ),
        )
        mocker.patch(
            "margot.services.pull.prepare_oci_retrieval",
            return_value=SimpleNamespace(
                normalized_uri=f"{REPOSITORY}:1.0.2+mosquitto-quadlet",
                package_type=PackageType.QUADLET,
                manifest={"artifactType": "application/vnd.org.margo.component.quadlet.v1+json"},
            ),
        )

        def pull(_prepared: Any, outdir: str, **_: Any) -> list[str]:
            return [str(write_tar(Path(outdir) / "bundle.tgz", quadlet_payload(root=None)))]

        mocker.patch("margot.services.pull.pull_prepared_context", side_effect=pull)

        result = runner.invoke(app, ["install", f"{REPOSITORY}:1.0.3", "--dry-run"])

        assert result.exit_code == 0
        assert "remote" in result.output
        assert not xdg.exists()


class TestInstall:
    """Successful installs from each source, with next-step commands printed and never run."""

    def test_project_install_with_yes_places_files_and_prints_start_commands(
        self, tmp_path: Path, systemctl: Any, xdg: Path, staging_tmp: Path
    ) -> None:
        """Should install the built project, print the start command, and clean staging."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0, result.output
        app_dir = xdg / "com-belden-mosquitto"
        assert (app_dir / "mosquitto.container").is_file()
        assert (app_dir / "conf" / "mosquitto.conf").is_file()
        assert "systemctl --user start mosquitto.service" in result.output
        assert _leftovers(staging_tmp) == []

    def test_install_never_starts_or_enables(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should call the session check, daemon-reload and one service check, in that order, and nothing else."""
        args, _ = _project_args(tmp_path)

        runner.invoke(app, ["install", *args, "--yes"])

        assert _systemd_calls(systemctl) == ["ensure_user_session", "daemon_reload", "unit_is_known:mosquitto.service"]

    def test_marker_is_written_with_installed_state(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should leave a marker in state 'installed' inside the application directory."""
        args, _ = _project_args(tmp_path)

        runner.invoke(app, ["install", *args, "--yes"])

        marker = json.loads((xdg / "com-belden-mosquitto" / MARKER_FILENAME).read_text(encoding="utf-8"))
        assert marker["state"] == "installed"

    def test_confirmed_install_on_a_terminal(self, tmp_path: Path, mocker: Any, systemctl: Any, xdg: Path) -> None:
        """Should install after an affirmative answer on a terminal."""
        mocker.patch("margot.console.is_interactive", return_value=True)
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args], input="y\n")

        assert result.exit_code == 0
        assert (xdg / "com-belden-mosquitto" / "mosquitto.container").is_file()

    def test_static_folder_install(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should install a pull --recursive folder with --yes."""
        folder = build_static_folder(tmp_path)

        result = runner.invoke(app, ["install", "--project-dir", str(folder), "--yes"])

        assert result.exit_code == 0, result.output
        assert (xdg / "com-belden-mosquitto" / "mosquitto.container").is_file()

    @mark.parametrize("name", ["array[string] app", "[Container] app"])
    def test_brackets_in_values_render_intact(self, tmp_path: Path, systemctl: Any, xdg: Path, name: str) -> None:
        """Should show values containing square brackets literally in the plan (rich-rendering rule)."""
        folder = build_static_folder(tmp_path, descriptor=app_description().replace("name: Eclipse Mosquitto", f'name: "{name}"'))

        result = runner.invoke(app, ["install", "--project-dir", str(folder), "--dry-run"])

        assert result.exit_code == 0
        assert name in result.output


class TestResultReport:
    """The printed result: directory on its own line, the start/status commands, the WantedBy=default.target timing."""

    def test_installed_directory_is_printed_on_its_own_line(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should print the application directory as a whole line, never folded into the message."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0, result.output
        assert str(xdg / "com-belden-mosquitto") in result.output.splitlines()

    def test_wanted_by_default_target_unit_gets_next_login_hint(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should say the service starts at the next login/boot when its unit declares WantedBy=default.target."""
        members = quadlet_payload()
        members["mosquitto-1.0.2_mosquitto-quadlet/mosquitto.container"] = (
            b"[Container]\nImage=docker.io/library/eclipse-mosquitto:2\n\n[Install]\nWantedBy=default.target\n"
        )
        project, build = build_project(tmp_path, archive_members=members)

        result = runner.invoke(app, ["install", "--project-dir", str(project), "--build-dir", str(build), "--yes"])

        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "mosquitto.service starts at the next login/boot" in flat
        assert "loginctl enable-linger" in flat

    def test_unit_without_wanted_by_gets_no_start_timing_hint(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should say nothing about login or boot start for a unit without WantedBy=default.target."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0, result.output
        assert "next login" not in result.output
        assert "WantedBy=" not in result.output

    def test_first_install_prints_no_restart_command(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should not mention restart on a fresh install."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0, result.output
        assert "systemctl --user restart" not in result.output

    def test_upgrade_prints_no_restart_hint(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should not print the old-unit or restart tip on upgrade, and print no restart command."""
        args, _ = _project_args(tmp_path)
        first = runner.invoke(app, ["install", *args, "--yes"])
        assert first.exit_code == 0, first.output

        second = runner.invoke(app, ["install", *args, "--yes"])

        assert second.exit_code == 0, second.output
        assert "keep the old unit files" not in second.output
        assert "systemctl --user restart" not in second.output
        assert "systemctl --user start mosquitto.service" in second.output

    def test_result_prints_no_startup_timeout_tip(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should not print the first-start timeout tip; that belongs in the docs, not the command output."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0, result.output
        assert "90 s" not in result.output
        assert "first start" not in result.output


PARAMETER_PORT = """parameters:
  mqttPort:
    value: 1883
    targets:
      - pointer: MQTT_PORT
        components:
          - mosquitto-quadlet
"""
PARAMETER_BRACKETS = """parameters:
  label:
    value: "[Container] array[string]"
    targets:
      - pointer: LABEL_TEXT
        components:
          - mosquitto-quadlet
"""
PARAMETER_UNVALUED = """parameters:
  mqttPort:
    targets:
      - pointer: MQTT_PORT
        components:
          - mosquitto-quadlet
"""


def _project_with(tmp_path: Path, parameters: str) -> list[str]:
    project, build = build_project(tmp_path, descriptor=app_description(parameters=parameters))
    return ["--project-dir", str(project), "--build-dir", str(build)]


def _mosquitto_dropin(xdg: Path) -> str:
    return (xdg / "com-belden-mosquitto" / "mosquitto.container.d" / "50-margot-parameters.conf").read_text(encoding="utf-8")


class TestParameters:
    """--set and the parameter table."""

    def test_set_without_equals_exits_2(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 2 for a --set argument that has no '=', before any work."""
        args = _project_with(tmp_path, PARAMETER_PORT)

        result = runner.invoke(app, ["install", *args, "--set", "mqttPort", "--yes"])

        assert result.exit_code == 2
        assert not xdg.exists()

    def test_unknown_set_name_exits_3_and_lists_the_applicable_names(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 3 for a --set name that is not applicable and list the applicable names."""
        args = _project_with(tmp_path, PARAMETER_PORT)

        result = runner.invoke(app, ["install", *args, "--set", "ghost=1", "--yes"])

        assert result.exit_code == 3
        assert "mqttPort" in result.output
        assert not xdg.exists()

    def test_newline_in_set_value_exits_3(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 3 when a --set value contains a newline."""
        args = _project_with(tmp_path, PARAMETER_PORT)

        result = runner.invoke(app, ["install", *args, "--set", "mqttPort=a\nb", "--yes"])

        assert result.exit_code == 3
        assert "newline" in result.output
        assert not xdg.exists()

    def test_repeated_set_last_wins_and_is_announced(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should keep the last value of a repeated --set name and say so."""
        args = _project_with(tmp_path, PARAMETER_PORT)

        result = runner.invoke(app, ["install", *args, "--set", "mqttPort=1", "--set", "mqttPort=2", "--yes"])

        assert result.exit_code == 0, result.output
        assert "given more than once" in result.output
        assert 'Environment="MQTT_PORT=2"' in _mosquitto_dropin(xdg)

    def test_dry_run_table_renders_brackets_and_types_literally(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should show a value with [ ] and array[string] intact in the parameter table."""
        args = _project_with(tmp_path, PARAMETER_BRACKETS)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "[Container] array[string]" in " ".join(result.output.split())
        assert "LABEL_TEXT" in result.output
        assert not xdg.exists()

    def test_dry_run_table_names_the_source_of_each_value(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should show whether the value comes from the descriptor or from --set."""
        args = _project_with(tmp_path, PARAMETER_PORT)

        plain = runner.invoke(app, ["install", *args, "--dry-run"])
        overridden = runner.invoke(app, ["install", *args, "--set", "mqttPort=1884", "--dry-run"])

        assert "descriptor" in plain.output
        assert "--set" in overridden.output
        assert "1884" in overridden.output

    def test_unvalued_parameter_is_reported_as_not_applied(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should warn that a parameter without a value is not applied and name it."""
        args = _project_with(tmp_path, PARAMETER_UNVALUED)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "not applied" in result.output
        assert "mqttPort" in result.output

    def test_install_with_set_writes_the_dropin_and_prints_no_visibility_tip(
        self, tmp_path: Path, systemctl: Any, xdg: Path
    ) -> None:
        """Should apply --set through the drop-in and print no tip about inspecting parameter values."""
        args = _project_with(tmp_path, PARAMETER_PORT)

        result = runner.invoke(app, ["install", *args, "--set", "mqttPort=1884", "--yes"])

        assert result.exit_code == 0, result.output
        assert 'Environment="MQTT_PORT=1884"' in _mosquitto_dropin(xdg)
        assert "systemctl --user show" not in result.output
        assert "systemctl --user cat" not in result.output

    def test_dry_run_with_set_changes_nothing(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should show the value in the plan and leave the host untouched."""
        args = _project_with(tmp_path, PARAMETER_PORT)

        result = runner.invoke(app, ["install", *args, "--set", "mqttPort=1884", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert not xdg.exists()
        assert systemctl.mock_calls == []


class TestQuadletDirPlan:
    """The plan states once that margot sets QUADLET_DIR to the application directory for every unit."""

    def test_plan_states_quadlet_dir_once_without_parameters(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should print one line naming QUADLET_DIR and the application directory, even with no parameters."""
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0, result.output
        expected = f"margot sets QUADLET_DIR={xdg / 'com-belden-mosquitto'} for every unit."
        assert result.output.splitlines().count(expected) == 1
        assert result.output.count("QUADLET_DIR") == 1

    def test_plan_keeps_the_directory_whole_on_one_line(self, tmp_path: Path, systemctl: Any, monkeypatch: Any) -> None:
        """Should keep a long application directory whole on one line, and keep brackets in it literal."""
        base = tmp_path / "a-very-long-configuration-directory-name-for-the-wrapping-check" / "[lit]"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(base))
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0, result.output
        expected = f"margot sets QUADLET_DIR={base / 'containers' / 'systemd' / 'com-belden-mosquitto'} for every unit."
        assert expected in result.output.splitlines()

    def test_plan_names_the_same_directory_with_parameters(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should keep one parameter table of descriptor parameters, and the QUADLET_DIR line outside it."""
        args = _project_with(tmp_path, PARAMETER_PORT)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0, result.output
        assert f"margot sets QUADLET_DIR={xdg / 'com-belden-mosquitto'} for every unit." in result.output.splitlines()
        assert "QUADLET_DIR" not in result.output.split("Parameters", 1)[1]


class TestGuards:
    """The install guards through the CLI: collision (exit 3, also in --dry-run), generator (exit 3), post-reload (exit 1)."""

    def test_collision_in_dry_run_exits_3_and_names_both_paths(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should refuse a unit already present elsewhere, even for --dry-run, naming both paths."""
        existing = xdg / "handmade" / "mosquitto.container"
        existing.parent.mkdir(parents=True)
        existing.write_text("[Container]\nImage=x\n", encoding="utf-8")
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 3
        assert str(existing) in result.output
        assert str(xdg / "com-belden-mosquitto" / "mosquitto.container") in result.output
        assert "same file name" in result.output
        assert not (xdg / "com-belden-mosquitto").exists()
        assert systemctl.mock_calls == []

    def test_collision_with_yes_exits_3_and_writes_nothing(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 3 with --yes too, and not reload systemd."""
        existing = xdg / "handmade" / "mosquitto.kube"
        existing.parent.mkdir(parents=True)
        existing.write_text("[Kube]\nYaml=x.yaml\n", encoding="utf-8")
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 3
        assert "same service name" in result.output
        assert "mosquitto.service" in result.output
        assert not (xdg / "com-belden-mosquitto").exists()
        assert systemctl.mock_calls == []

    def test_generator_rejection_exits_3_with_its_message_and_writes_nothing(
        self, tmp_path: Path, systemctl: Any, xdg: Path, install_host: Any
    ) -> None:
        """Should exit 3 with the trimmed generator message before the host is touched."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1,
            stderr="quadlet-generator[1]: converting \"mosquitto.container\": unknown key 'Imag'\n"
            "quadlet-generator[1]: processing encountered some errors",
        )
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 3
        assert "unknown key 'Imag'" in result.output
        assert not (xdg / "com-belden-mosquitto").exists()
        assert systemctl.mock_calls == []

    def test_generator_output_stays_out_of_stdout(self, tmp_path: Path, systemctl: Any, xdg: Path, install_host: Any) -> None:
        """Should not print the generator's service blocks on stdout, valid tree or not."""
        install_host.generator.side_effect = lambda *_: GeneratorRun(returncode=0, stderr="")
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0
        assert "---mosquitto.service---" not in result.output

    def test_missing_generator_warns_once_and_install_continues(
        self, tmp_path: Path, systemctl: Any, xdg: Path, install_host: Any
    ) -> None:
        """Should print one warning and still install when the Quadlet generator is not found."""
        install_host.binary.return_value = None
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0
        assert result.output.count("Quadlet generator") == 1
        assert (xdg / "com-belden-mosquitto" / "mosquitto.container").is_file()

    def test_missing_service_after_reload_exits_1_with_the_hint(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should exit 1 naming the service, the unit file and the diagnostics when systemd does not know it."""
        systemctl.unit_is_known.side_effect = lambda service: service != "mosquitto.service"
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 1
        assert "mosquitto.service" in result.output
        assert str(xdg / "com-belden-mosquitto" / "mosquitto.container") in result.output
        assert "journalctl --user -b -t quadlet-generator" in result.output
        assert "nothing was rolled back" in result.output.lower()


def _unresolved_stderr(*references: tuple[str, str], errors: tuple[str, ...] = ()) -> str:
    """Generator stderr as the host prints it when units refer to units outside the staged tree."""
    lines = [
        "quadlet-generator[1]: Loading source unit file /staging/mosquitto.container",
        "quadlet-generator[1]: Loading source drop-in file /staging/mosquitto.container.d/50-margot-parameters.conf",
    ]
    lines.extend(
        f'quadlet-generator[1]: converting "{unit}": requested Quadlet unit {name} was not found' for unit, name in references
    )
    lines.extend(errors)
    lines.append("quadlet-generator[1]: processing encountered some errors")
    return "\n".join(lines)


WARNING_START = "mosquitto.container references owner.network, which is not installed on this host."


def _flat(output: str) -> str:
    """Collapse rich line wrapping so a long warning can be matched as one sentence."""
    return " ".join(output.split())


class TestUnresolvedReferences:
    """A unit may refer to a unit that is not in the application."""

    def test_missing_reference_prints_one_warning_and_exits_0(
        self, tmp_path: Path, systemctl: Any, xdg: Path, install_host: Any
    ) -> None:
        """Should install with exit 0 and print the warning exactly once, naming the unit and the missing network."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_unresolved_stderr(("mosquitto.container", "owner.network"))
        )
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0
        text = _flat(result.output)
        assert text.count(WARNING_START) == 1
        assert "mosquitto.service is generated once owner.network is installed" in text
        assert (xdg / "com-belden-mosquitto" / "mosquitto.container").is_file()
        assert "unit_is_known:mosquitto.service" not in _systemd_calls(systemctl)

    def test_missing_reference_dry_run_warns_and_writes_nothing(
        self, tmp_path: Path, systemctl: Any, xdg: Path, install_host: Any
    ) -> None:
        """Should show the same warning under --dry-run and change nothing on the host."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_unresolved_stderr(("mosquitto.container", "owner.network"))
        )
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--dry-run"])

        assert result.exit_code == 0
        assert _flat(result.output).count(WARNING_START) == 1
        assert not (xdg / "com-belden-mosquitto").exists()
        assert systemctl.mock_calls == []

    def test_reference_to_an_installed_unit_prints_no_warning(
        self, tmp_path: Path, systemctl: Any, xdg: Path, install_host: Any
    ) -> None:
        """Should stay silent when the referenced network is already on the host."""
        existing = xdg / "handmade" / "owner.network"
        existing.parent.mkdir(parents=True)
        existing.write_text("[Network]\n", encoding="utf-8")
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_unresolved_stderr(("mosquitto.container", "owner.network"))
        )
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0
        assert "not installed on this host" not in _flat(result.output)

    def test_real_error_beside_a_reference_exits_3_and_shows_only_the_error(
        self, tmp_path: Path, systemctl: Any, xdg: Path, install_host: Any
    ) -> None:
        """Should exit 3 with the real error line and leave out the reference that is merely unresolved."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1,
            stderr=_unresolved_stderr(
                ("mosquitto.container", "owner.network"),
                errors=("quadlet-generator[1]: converting \"other.container\": unsupported key 'NoSuchKey'",),
            ),
        )
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 3
        assert "NoSuchKey" in result.output
        assert "owner.network was not found" not in result.output
        assert not (xdg / "com-belden-mosquitto").exists()
        assert systemctl.mock_calls == []


VOLUME_WARNING_START = "mosquitto.container references owner.volume, which is not installed on this host."


class TestMissingServiceAfterWrite:
    """A unit whose second reference is missing is installed with a warning; a real error is exit 1."""

    @fixture
    def cat_fails_for_mosquitto(self, systemctl: Any) -> Any:
        """systemd does not know mosquitto.service after reload; every other service is known."""
        systemctl.unit_is_known.side_effect = lambda service: service != "mosquitto.service"
        return systemctl

    def test_missing_second_reference_exits_0_and_prints_one_warning(
        self, tmp_path: Path, xdg: Path, install_host: Any, cat_fails_for_mosquitto: Any
    ) -> None:
        """Should exit 0 and print one warning naming the missing volume; the service is not required."""
        existing = xdg / "handmade" / "owner.network"
        existing.parent.mkdir(parents=True)
        existing.write_text("[Network]\n", encoding="utf-8")
        install_host.generator.side_effect = answer_by_run(
            staged=GeneratorRun(returncode=1, stderr=_unresolved_stderr(("mosquitto.container", "owner.network"))),
            host=GeneratorRun(returncode=1, stderr=_unresolved_stderr(("mosquitto.container", "owner.volume"))),
        )
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 0
        text = _flat(result.output)
        assert text.count(VOLUME_WARNING_START) == 1
        assert "mosquitto.service is generated once owner.volume is installed" in text
        assert "nothing was rolled back" not in text.lower()
        assert (xdg / "com-belden-mosquitto" / "mosquitto.container").is_file()

    def test_real_error_behind_the_reference_exits_1_and_shows_the_error(
        self, tmp_path: Path, xdg: Path, install_host: Any, cat_fails_for_mosquitto: Any
    ) -> None:
        """Should exit 1 with the real error line, and say that the files were kept."""
        error = "quadlet-generator[1]: converting \"mosquitto.container\": unsupported key 'NoSuchKey' in group 'Container'"
        install_host.generator.side_effect = answer_by_run(
            staged=GeneratorRun(returncode=0, stderr=""),
            host=GeneratorRun(
                returncode=1, stderr=_unresolved_stderr(("mosquitto.container", "owner.volume"), errors=(error,))
            ),
        )
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 1
        assert "NoSuchKey" in result.output
        assert "owner.volume" not in result.output
        assert "nothing was rolled back" in _flat(result.output).lower()
        assert (xdg / "com-belden-mosquitto" / "mosquitto.container").is_file()
