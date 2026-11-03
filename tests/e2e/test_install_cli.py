"""E2E tests for `margot install` through the CLI (CliRunner), with systemctl and the registry mocked.

Exit codes follow the taxonomy in docs/exit-codes.md: 2 usage, 3 validation, 4 registry, 1 host/declined.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pytest import fixture, mark
from typer.testing import CliRunner

from margot.domain.install import MARKER_FILENAME
from margot.domain.models import PackageType
from margot.infra.credentials import CredentialsExpiredError
from margot.main import app
from tests.integration._install_helpers import (
    REPOSITORY,
    app_description,
    build_project,
    build_static_folder,
    quadlet_payload,
    write_tar,
)

runner = CliRunner()


def _completed(returncode: int = 0, stderr: str = "") -> Any:
    return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


@fixture
def systemctl(mocker: Any) -> Any:
    """systemctl --user is available and succeeds; every call is recorded."""
    mocker.patch("margot.infra.systemd.which", return_value="/usr/bin/systemctl")
    return mocker.patch("margot.infra.systemd.run", return_value=_completed(0))


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

    def test_help_lists_the_options_without_set(self) -> None:
        """Should show --dry-run, --yes and --profile, and no --set yet (Step 2)."""
        result = runner.invoke(app, ["install", "--help"])

        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--yes" in result.output
        assert "--profile" in result.output
        assert "--set" not in result.output


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

    def test_unusable_user_session_exits_1(self, tmp_path: Path, mocker: Any, xdg: Path) -> None:
        """Should exit 1 and name the user session when systemctl --user cannot answer."""
        mocker.patch("margot.infra.systemd.which", return_value="/usr/bin/systemctl")
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "Failed to connect to bus"))
        args, _ = _project_args(tmp_path)

        result = runner.invoke(app, ["install", *args, "--yes"])

        assert result.exit_code == 1
        assert "user session" in result.output
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
        systemctl.assert_not_called()

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
        """Should call systemctl only for show-environment and daemon-reload."""
        args, _ = _project_args(tmp_path)

        runner.invoke(app, ["install", *args, "--yes"])

        assert [call.args[0][-1] for call in systemctl.call_args_list] == ["show-environment", "daemon-reload"]

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
