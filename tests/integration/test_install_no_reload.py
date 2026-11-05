"""Integration tests for apply_install(reload=False), the service behind `margot install --no-reload`.

The systemd user manager is never contacted with reload=False. The tests patch the public functions of
``margot.infra.systemd`` (session check, daemon-reload, unit check) and assert on their calls, so they
keep working when the transport underneath changes. Placement is compared with a normal install of the
same project under the same Quadlet root.
"""

from dataclasses import replace
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any

from pytest import fixture, mark, raises

from margot.domain.install import MARKER_FILENAME
from margot.infra.systemd import SystemdError
from margot.services import install as install_service
from tests.integration._install_helpers import MOSQUITTO_CONTAINER, build_project, quadlet_payload

pytestmark = mark.usefixtures("install_host")

APP = "com-belden-mosquitto"


@fixture
def systemd_calls(mocker: Any) -> SimpleNamespace:
    """The three public systemd functions the install path can call, mocked and recorded."""
    return SimpleNamespace(
        ensure=mocker.patch("margot.infra.systemd.ensure_user_session"),
        reload=mocker.patch("margot.infra.systemd.daemon_reload"),
        known=mocker.patch("margot.infra.systemd.unit_is_known", return_value=True),
    )


def _prepare(base: Path, members: dict[str, bytes] | None = None) -> Any:
    """Prepare an install of a fresh built project under ``base`` (one base per project)."""
    project, build = build_project(base, archive_members=members)
    return _prepare_built(project, build)


def _prepare_built(project: Path, build: Path) -> Any:
    return install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)


def _apply(prepared: Any, root: Path, *, reload: bool) -> Any:
    try:
        return install_service.apply_install(prepared, root=root, reload=reload)
    finally:
        prepared.cleanup()


def _snapshot(app_dir: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Every file under the application directory except the marker, and the marker without its timestamp."""
    files = {
        path.relative_to(app_dir).as_posix(): path.read_bytes()
        for path in sorted(app_dir.rglob("*"))
        if path.is_file() and path.name != MARKER_FILENAME
    }
    marker = json.loads((app_dir / MARKER_FILENAME).read_text(encoding="utf-8"))
    marker.pop("installedAt")
    return files, marker


class TestNoSystemdContact:
    """reload=False never calls the session check, the reload or the unit check."""

    def test_no_reload_calls_none_of_the_systemd_functions(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should place the files without calling ensure_user_session, daemon_reload or unit_is_known."""
        _apply(_prepare(tmp_path), install_host.root, reload=False)

        systemd_calls.ensure.assert_not_called()
        systemd_calls.reload.assert_not_called()
        systemd_calls.known.assert_not_called()
        assert (install_host.root / APP / "mosquitto.container").is_file()

    def test_default_reload_calls_session_reload_and_unit_check_once(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should keep the default behaviour: one session check, one reload, one unit check per service."""
        _apply(_prepare(tmp_path), install_host.root, reload=True)

        systemd_calls.ensure.assert_called_once_with()
        systemd_calls.reload.assert_called_once_with()
        systemd_calls.known.assert_called_once_with("mosquitto.service")


class TestSameLayoutAsNormalInstall:
    """A --no-reload install leaves the same files, drop-ins and marker as a normal install."""

    def test_no_reload_tree_matches_normal_install(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should produce identical files, drop-ins and marker (state installed) in both modes."""
        project, build = build_project(tmp_path)
        _apply(_prepare_built(project, build), install_host.root, reload=False)
        app_dir = install_host.root / APP
        without_reload = _snapshot(app_dir)
        shutil.rmtree(app_dir)

        _apply(_prepare_built(project, build), install_host.root, reload=True)
        with_reload = _snapshot(app_dir)

        assert without_reload == with_reload
        assert without_reload[1]["state"] == "installed"
        assert "mosquitto.container.d/50-margot-parameters.conf" in without_reload[0]

    def test_dropin_quadlet_dir_names_the_application_directory(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should write QUADLET_DIR pointing at the real application directory without systemd."""
        _apply(_prepare(tmp_path), install_host.root, reload=False)

        dropin = (install_host.root / APP / "mosquitto.container.d" / "50-margot-parameters.conf").read_text(encoding="utf-8")
        assert f'Environment="QUADLET_DIR={install_host.root / APP}"' in dropin


class TestOwnershipStillApplies:
    """The ownership rules run with --no-reload, before any write."""

    def test_directory_without_marker_is_refused_with_no_reload(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should raise ValueError for a foreign directory and leave it untouched."""
        app_dir = install_host.root / APP
        app_dir.mkdir(parents=True)
        (app_dir / "hand-written.container").write_text("x", encoding="utf-8")
        prepared = _prepare(tmp_path)

        with raises(ValueError, match=r"not installed by margot"):
            _apply(prepared, install_host.root, reload=False)

        assert [p.name for p in app_dir.iterdir()] == ["hand-written.container"]
        systemd_calls.ensure.assert_not_called()

    def test_upgrade_with_no_reload_removes_stale_files(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should delete a file the previous marker recorded but the new payload no longer ships."""
        _apply(_prepare(tmp_path / "a"), install_host.root, reload=True)
        app_dir = install_host.root / APP
        (app_dir / "old.conf").write_text("stale", encoding="utf-8")
        marker_path = app_dir / MARKER_FILENAME
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        data["components"][0]["files"].append("old.conf")
        marker_path.write_text(json.dumps(data), encoding="utf-8")

        _apply(_prepare(tmp_path / "b"), install_host.root, reload=False)

        assert not (app_dir / "old.conf").exists()
        assert json.loads(marker_path.read_text(encoding="utf-8"))["state"] == "installed"


class TestResultWithoutReload:
    """What InstallResult reports when systemd was not contacted."""

    def test_result_is_marked_not_reloaded_with_unverified_services(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should set reloaded False, list the planned service and report no warnings."""
        result = _apply(_prepare(tmp_path), install_host.root, reload=False)

        assert result.reloaded is False
        assert result.services == ("mosquitto.service",)
        assert result.start_services == ("mosquitto.service",)
        assert result.warnings == ()

    def test_deferred_services_are_excluded_without_reload(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should leave deferred services out of services, start_services and wanted_services."""
        prefix = "mosquitto-1.0.2_mosquitto-quadlet/"
        members = {
            f"{prefix}a.container": MOSQUITTO_CONTAINER,
            f"{prefix}b.container": MOSQUITTO_CONTAINER,
            f"{prefix}mosquitto.container": MOSQUITTO_CONTAINER,
        }
        prepared = _prepare(tmp_path, members)
        prepared = replace(prepared, deferred=("b.service",))

        result = _apply(prepared, install_host.root, reload=False)

        assert result.services == ("a.service", "mosquitto.service")
        assert result.start_services == ("a.service", "mosquitto.service")
        assert result.wanted_services == ()
        assert "b.container" in result.unit_files
        assert (install_host.root / APP / "b.container").is_file()
        systemd_calls.known.assert_not_called()


class TestResultWithReload:
    """The default path reports that systemd was contacted."""

    def test_default_result_is_reloaded(self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace) -> None:
        """Should set reloaded True and keep the verified service list."""
        result = _apply(_prepare(tmp_path), install_host.root, reload=True)

        assert result.reloaded is True
        assert result.services == ("mosquitto.service",)

    def test_failed_reload_with_reload_raises_systemd_error(
        self, tmp_path: Path, install_host: Any, systemd_calls: SimpleNamespace
    ) -> None:
        """Should keep the reload failure as SystemdError when reload is True."""
        systemd_calls.reload.side_effect = SystemdError("daemon-reload failed")
        prepared = _prepare(tmp_path)

        with raises(SystemdError, match=r"nothing was rolled back"):
            _apply(prepared, install_host.root, reload=True)
