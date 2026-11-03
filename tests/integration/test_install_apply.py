"""Integration tests for services/install.py::apply_install with a mocked systemctl and a tmp XDG root.

Covers placement, the marker states, ownership refusals, upgrade cleanup, the failure phases, and the
guarantee that install never starts, enables or stops anything.
"""

import json
from pathlib import Path
from typing import Any

from pytest import fixture, raises

from margot.domain.install import MARKER_FILENAME
from margot.infra.systemd import SystemdError
from margot.services import install as install_service
from tests.integration._install_helpers import build_project, quadlet_payload


def _completed(returncode: int = 0, stderr: str = "") -> Any:
    return type("Completed", (), {"returncode": returncode, "stdout": "", "stderr": stderr})()


@fixture
def systemctl(mocker: Any) -> Any:
    """Mock every systemctl --user call as successful, recording the argv list."""
    mocker.patch("margot.infra.systemd.which", return_value="/usr/bin/systemctl")
    return mocker.patch("margot.infra.systemd.run", return_value=_completed(0))


@fixture
def xdg(tmp_path: Path, monkeypatch: Any) -> Path:
    """The Quadlet root for this test: <tmp>/xdg/containers/systemd."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "containers" / "systemd"


def _prepare(tmp_path: Path, **kwargs: Any) -> Any:
    project, build = build_project(tmp_path)
    return install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None, **kwargs)


def _argv_list(systemctl: Any) -> list[list[str]]:
    return [call.args[0] for call in systemctl.call_args_list]


class TestFreshInstall:
    """First install of an application directory."""

    def test_files_are_placed_with_relative_layout(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should write each payload file at its relative path under the application directory."""
        prepared = _prepare(tmp_path)
        try:
            install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        app = xdg / "com-belden-mosquitto"
        assert (app / "mosquitto.container").read_bytes().startswith(b"[Container]")
        assert (app / "conf" / "mosquitto.conf").is_file()

    def test_marker_ends_installed_with_components_and_services(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should write the marker in state 'installed' with the component files and services."""
        prepared = _prepare(tmp_path)
        try:
            result = install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        marker = json.loads((xdg / "com-belden-mosquitto" / MARKER_FILENAME).read_text(encoding="utf-8"))
        assert marker["state"] == "installed"
        assert marker["profileId"] == "quadlet-v1"
        assert marker["services"] == ["mosquitto.service"]
        assert sorted(marker["components"][0]["files"]) == [
            "conf/mosquitto.conf",
            "mosquitto.container",
            "mosquitto.container.d/50-margot-parameters.conf",
        ]
        assert result.services == ("mosquitto.service",)

    def test_only_daemon_reload_is_called_and_never_start_or_enable(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should call systemctl with show-environment and daemon-reload only, never start/enable/stop."""
        prepared = _prepare(tmp_path)
        try:
            install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        commands = [argv[-1] for argv in _argv_list(systemctl)]
        assert commands == ["show-environment", "daemon-reload"]
        assert not any(word in argv for argv in _argv_list(systemctl) for word in ("start", "enable", "stop", "restart"))

    def test_start_targets_are_reported_for_printing_only(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should report the start commands without running them."""
        prepared = _prepare(tmp_path)
        try:
            result = install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert result.start_services == ("mosquitto.service",)


class TestOwnership:
    """margot never writes into a directory without its marker, nor into another profile's (sprint-13 §3.7)."""

    def test_directory_without_marker_is_refused_and_untouched(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should refuse an application directory that margot did not create, leaving it unchanged."""
        app = xdg / "com-belden-mosquitto"
        app.mkdir(parents=True)
        (app / "hand-written.container").write_text("x", encoding="utf-8")
        prepared = _prepare(tmp_path)
        try:
            with raises(ValueError, match=r"not installed by margot"):
                install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert sorted(p.name for p in app.iterdir()) == ["hand-written.container"]
        assert [argv[-1] for argv in _argv_list(systemctl)] == ["show-environment"]

    def test_plan_prepared_for_another_root_is_refused(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should refuse to apply a plan whose QUADLET_DIR names another directory, so the drop-in always matches the install."""
        prepared = _prepare(tmp_path)
        try:
            with raises(ValueError, match=r"prepared for"):
                install_service.apply_install(prepared, root=tmp_path / "elsewhere")
        finally:
            prepared.cleanup()

        assert not (tmp_path / "elsewhere").exists()

    def test_recorded_other_profile_is_refused(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should name the recorded profile when the marker belongs to another profile."""
        first = _prepare(tmp_path / "a")
        try:
            install_service.apply_install(first, root=xdg)
        finally:
            first.cleanup()
        marker_path = xdg / "com-belden-mosquitto" / MARKER_FILENAME
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        data["profileId"] = "quadlet-other"
        marker_path.write_text(json.dumps(data), encoding="utf-8")
        second = _prepare(tmp_path / "b")
        try:
            with raises(ValueError, match=r"quadlet-other"):
                install_service.apply_install(second, root=xdg)
        finally:
            second.cleanup()


class TestUpgrade:
    """Re-running install over an existing margot installation."""

    def test_stale_file_listed_by_previous_marker_is_removed(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should delete a file the previous marker listed but the new payload no longer ships."""
        first = _prepare(tmp_path / "a")
        try:
            install_service.apply_install(first, root=xdg)
        finally:
            first.cleanup()
        app = xdg / "com-belden-mosquitto"
        (app / "old.conf").write_text("stale", encoding="utf-8")
        data = json.loads((app / MARKER_FILENAME).read_text(encoding="utf-8"))
        data["components"][0]["files"].append("old.conf")
        (app / MARKER_FILENAME).write_text(json.dumps(data), encoding="utf-8")
        second = _prepare(tmp_path / "b")
        try:
            install_service.apply_install(second, root=xdg)
        finally:
            second.cleanup()

        assert not (app / "old.conf").exists()

    def test_user_file_not_listed_in_marker_is_kept(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should never touch a file that margot did not record, such as a hand-written drop-in."""
        first = _prepare(tmp_path / "a")
        try:
            install_service.apply_install(first, root=xdg)
        finally:
            first.cleanup()
        app = xdg / "com-belden-mosquitto"
        (app / "90-local.conf").write_text("mine", encoding="utf-8")
        second = _prepare(tmp_path / "b")
        try:
            install_service.apply_install(second, root=xdg)
        finally:
            second.cleanup()

        assert (app / "90-local.conf").read_text(encoding="utf-8") == "mine"

    def test_interrupted_install_can_be_run_again(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should accept a marker left in state 'installing' by an earlier failed run."""
        first = _prepare(tmp_path / "a")
        try:
            install_service.apply_install(first, root=xdg)
        finally:
            first.cleanup()
        marker_path = xdg / "com-belden-mosquitto" / MARKER_FILENAME
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        data["state"] = "installing"
        marker_path.write_text(json.dumps(data), encoding="utf-8")
        second = _prepare(tmp_path / "b")
        try:
            install_service.apply_install(second, root=xdg)
        finally:
            second.cleanup()

        assert json.loads(marker_path.read_text(encoding="utf-8"))["state"] == "installed"


class TestFailurePhases:
    """Each failure phase reports what happened and changes nothing it should not."""

    def test_unusable_user_session_writes_nothing(self, tmp_path: Path, mocker: Any, xdg: Path) -> None:
        """Should stop before any write when the systemd user session is not usable."""
        mocker.patch("margot.infra.systemd.which", return_value="/usr/bin/systemctl")
        mocker.patch("margot.infra.systemd.run", return_value=_completed(1, "Failed to connect to bus"))
        prepared = _prepare(tmp_path)
        try:
            with raises(SystemdError, match=r"user session"):
                install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert not xdg.exists()

    def test_failed_reload_keeps_files_and_reports_them(self, tmp_path: Path, mocker: Any, xdg: Path) -> None:
        """Should report the failed daemon-reload, keep the written files and not roll back."""
        mocker.patch("margot.infra.systemd.which", return_value="/usr/bin/systemctl")
        mocker.patch(
            "margot.infra.systemd.run",
            side_effect=[_completed(0), _completed(1, "reload exploded")],
        )
        prepared = _prepare(tmp_path)
        try:
            with raises(SystemdError, match=r"daemon-reload failed.*reload exploded.*nothing was rolled back"):
                install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        app = xdg / "com-belden-mosquitto"
        assert (app / "mosquitto.container").is_file()
        assert json.loads((app / MARKER_FILENAME).read_text(encoding="utf-8"))["state"] == "installed"


class TestResultHints:
    """What the result reports for the printed hints: upgrade and WantedBy=default.target (sprint-13 §3.7)."""

    def test_fresh_install_is_not_an_upgrade(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should report upgraded=False when no marker existed before."""
        prepared = _prepare(tmp_path)
        try:
            result = install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert result.upgraded is False

    def test_second_install_is_an_upgrade(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should report upgraded=True when a margot marker of the same profile already exists."""
        first = _prepare(tmp_path / "a")
        try:
            install_service.apply_install(first, root=xdg)
        finally:
            first.cleanup()
        second = _prepare(tmp_path / "b")
        try:
            result = install_service.apply_install(second, root=xdg)
        finally:
            second.cleanup()

        assert result.upgraded is True

    def test_unit_wanted_by_default_target_is_reported(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should list the service whose unit file declares WantedBy=default.target."""
        members = quadlet_payload()
        members["mosquitto-1.0.2_mosquitto-quadlet/mosquitto.container"] = (
            b"[Container]\nImage=docker.io/library/eclipse-mosquitto:2\n\n[Install]\nWantedBy=default.target\n"
        )
        project, build = build_project(tmp_path, archive_members=members)
        prepared = install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)
        try:
            result = install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert result.wanted_services == ("mosquitto.service",)

    def test_unit_without_wanted_by_default_target_is_not_reported(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should report no WantedBy service when the unit file does not name default.target."""
        prepared = _prepare(tmp_path)
        try:
            result = install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert result.wanted_services == ()
