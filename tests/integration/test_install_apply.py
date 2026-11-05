"""Integration tests for services/install.py::apply_install with a mocked systemd user manager and a tmp XDG root.

Covers placement, the marker states, ownership refusals, upgrade cleanup, the failure phases, and the
guarantee that install never starts, enables or stops anything.
"""

import json
from pathlib import Path
from typing import Any

from pytest import fixture, mark, raises

from margot.domain.install import MARKER_FILENAME
from margot.infra.systemd import SystemdError
from margot.services import install as install_service
from tests.integration._install_helpers import build_project, quadlet_payload

pytestmark = mark.usefixtures("install_host")


@fixture
def systemctl(mocker: Any) -> Any:
    """The systemd user manager answers every call. The three systemd functions are children of one mock.

    The order of calls is ``systemctl.mock_calls``; each entry's name is the function called.
    """
    manager = mocker.Mock()
    manager.unit_is_known.return_value = True
    mocker.patch("margot.infra.systemd.ensure_user_session", manager.ensure_user_session)
    mocker.patch("margot.infra.systemd.daemon_reload", manager.daemon_reload)
    mocker.patch("margot.infra.systemd.unit_is_known", manager.unit_is_known)
    return manager


@fixture
def xdg(tmp_path: Path, monkeypatch: Any) -> Path:
    """The Quadlet root for this test: <tmp>/xdg/containers/systemd."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "containers" / "systemd"


def _prepare(tmp_path: Path, **kwargs: Any) -> Any:
    project, build = build_project(tmp_path)
    return install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None, **kwargs)


def _called(systemctl: Any) -> list[str]:
    """The names of the systemd functions called, in order."""
    return [call[0] for call in systemctl.mock_calls]


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

    def test_only_session_check_reload_and_service_check_reach_systemd(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should call the session check, daemon-reload and one service check, in that order, and nothing else."""
        prepared = _prepare(tmp_path)
        try:
            install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert _called(systemctl) == ["ensure_user_session", "daemon_reload", "unit_is_known"]
        assert systemctl.unit_is_known.call_args.args == ("mosquitto.service",)

    def test_start_targets_are_reported_for_printing_only(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should report the start commands without running them."""
        prepared = _prepare(tmp_path)
        try:
            result = install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert result.start_services == ("mosquitto.service",)


class TestOwnership:
    """margot never writes into a directory without its marker, nor into another profile's."""

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
        assert _called(systemctl) == ["ensure_user_session"]

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

    def test_unusable_user_session_writes_nothing(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should stop before any write when the systemd user session is not usable."""
        systemctl.ensure_user_session.side_effect = SystemdError("The systemd user session is not reachable (tried: x).")
        prepared = _prepare(tmp_path)
        try:
            with raises(SystemdError, match=r"user session"):
                install_service.apply_install(prepared, root=xdg)
        finally:
            prepared.cleanup()

        assert not xdg.exists()

    def test_failed_reload_keeps_files_and_reports_them(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should report the failed daemon-reload, keep the written files and not roll back."""
        systemctl.daemon_reload.side_effect = SystemdError("systemd daemon-reload failed: reload exploded")
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
    """What the result reports for the printed WantedBy=default.target hint."""

    def test_second_install_is_applied_over_the_first(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should accept a second install of the same profile over an existing margot marker."""
        first = _prepare(tmp_path / "a")
        try:
            install_service.apply_install(first, root=xdg)
        finally:
            first.cleanup()
        second = _prepare(tmp_path / "b")
        try:
            install_service.apply_install(second, root=xdg)
        finally:
            second.cleanup()

        assert json.loads((xdg / "com-belden-mosquitto" / MARKER_FILENAME).read_text(encoding="utf-8"))["state"] == "installed"

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
