"""Integration tests for the Step 3 guards of `margot install` (sprint-13 §3.10).

Guard 1 (unit-name collision) and guard 2 (Quadlet generator dry-run) run in prepare_install, so
--dry-run exercises them too. Guard 3 (systemd must know every service after daemon-reload) runs in
apply_install. systemctl and the generator are mocked; Quadlet roots are real directories under tmp_path.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pytest import mark, raises

from margot.domain.install import MARKER_FILENAME
from margot.infra.systemd import GeneratorCheck, SystemdError
from margot.services import install as install_service
from tests.integration._install_helpers import build_project

pytestmark = mark.usefixtures("install_host")

APP = "com-belden-mosquitto"


def _completed(returncode: int = 0, stderr: str = "") -> Any:
    return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


def _systemctl(mocker: Any, missing: frozenset[str] = frozenset()) -> Any:
    """systemctl --user: every call succeeds except `cat` of a service listed in ``missing``."""
    mocker.patch("margot.infra.systemd.which", return_value="/usr/bin/systemctl")

    def run(argv: list[str], **_kwargs: Any) -> Any:
        if argv[2] == "cat" and argv[3] in missing:
            return _completed(1, f"Unit {argv[3]} could not be found.")
        return _completed(0)

    return mocker.patch("margot.infra.systemd.run", side_effect=run)


def _unit(root: Path, folder: str, name: str, content: str = "[Container]\nImage=x\n") -> Path:
    """Write a unit file into a sibling directory of the Quadlet root and return it."""
    path = root / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _marker(root: Path, folder: str) -> None:
    (root / folder).mkdir(parents=True, exist_ok=True)
    (root / folder / MARKER_FILENAME).write_text(json.dumps({"schema": 1, "appId": folder}), encoding="utf-8")


def _prepare(tmp_path: Path) -> Any:
    project, build = build_project(tmp_path)
    return install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)


def _tree(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) if root.exists() else []


class TestUnitNameCollision:
    """Guard 1: a unit that already exists elsewhere in the Quadlet search path is refused before any write."""

    def test_hand_written_unit_with_the_same_file_name_is_refused(self, tmp_path: Path, install_host: Any) -> None:
        """Should refuse with exit 3 semantics and name both the new and the existing path."""
        existing = _unit(install_host.root, "handmade", "mosquitto.container")

        with raises(ValueError, match=r"same file name") as info:
            _prepare(tmp_path)

        message = str(info.value)
        assert str(existing) in message
        assert str(install_host.root / APP / "mosquitto.container") in message
        assert "same file name" in message

    def test_sibling_margot_application_with_the_same_unit_is_refused(self, tmp_path: Path, install_host: Any) -> None:
        """Should refuse a unit that a different margot application already installed."""
        _marker(install_host.root, "com-other-app")
        existing = _unit(install_host.root, "com-other-app", "mosquitto.container")

        with raises(ValueError, match=r"same file name") as info:
            _prepare(tmp_path)

        assert str(existing) in str(info.value)

    def test_same_service_name_from_a_kube_unit_is_refused(self, tmp_path: Path, install_host: Any) -> None:
        """Should refuse a .kube unit whose generated service equals the one the install would generate."""
        existing = _unit(install_host.root, "handmade", "mosquitto.kube", "[Kube]\nYaml=x.yaml\n")

        with raises(ValueError, match=r"same service name") as info:
            _prepare(tmp_path)

        message = str(info.value)
        assert "mosquitto.service" in message
        assert str(existing) in message

    def test_a_unit_in_the_xdg_runtime_root_is_refused(self, tmp_path: Path, install_host: Any, monkeypatch: Any) -> None:
        """Should check the runtime root too, which Quadlet reads first."""
        runtime = tmp_path / "run"
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        existing = _unit(runtime / "containers", "systemd", "mosquitto.container")

        with raises(ValueError, match=r"same file name") as info:
            _prepare(tmp_path)

        assert str(existing) in str(info.value)

    def test_a_unit_in_a_system_root_is_refused(self, tmp_path: Path, install_host: Any) -> None:
        """Should check the per-user system root (/etc, /usr/share, here redirected to tmp)."""
        existing = _unit(install_host.system / "etc", "1000", "mosquitto.container")

        with raises(ValueError, match=r"same file name") as info:
            _prepare(tmp_path)

        assert str(existing) in str(info.value)

    def test_hidden_marker_drop_in_and_non_unit_files_do_not_collide(self, tmp_path: Path, install_host: Any) -> None:
        """Should install normally when the search path holds only ignored names."""
        _unit(install_host.root, "com-other-app", ".mosquitto.container")
        _unit(install_host.root, "com-other-app", "mosquitto.container.d/50-x.conf")
        _unit(install_host.root, "com-other-app", "mosquitto.conf")
        _marker(install_host.root, "com-other-app")

        prepared = _prepare(tmp_path)
        prepared.cleanup()

    def test_upgrade_inside_the_own_directory_is_allowed(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should accept a unit already in the application's own directory (an upgrade)."""
        _systemctl(mocker)
        first = _prepare(tmp_path / "a")
        try:
            install_service.apply_install(first, root=install_host.root)
        finally:
            first.cleanup()

        second = _prepare(tmp_path / "b")
        try:
            install_service.apply_install(second, root=install_host.root)
        finally:
            second.cleanup()

        assert (install_host.root / APP / "mosquitto.container").is_file()

    def test_refusal_writes_nothing(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should leave the Quadlet root unchanged after a collision is refused."""
        _unit(install_host.root, "handmade", "mosquitto.container")
        before = _tree(install_host.root)
        run = _systemctl(mocker)

        with raises(ValueError, match=r"same file name"):
            _prepare(tmp_path)

        assert _tree(install_host.root) == before
        assert not (install_host.root / APP).exists()
        run.assert_not_called()


class TestGeneratorValidation:
    """Guard 2: the staged tree is validated by the Quadlet generator before the host is touched."""

    def test_the_generator_validates_the_units_drop_ins_and_bundled_files(self, tmp_path: Path, install_host: Any) -> None:
        """Should hand the generator the full merged tree: units, bundled files and the drop-in with QUADLET_DIR."""
        seen: dict[str, Any] = {}

        def capture(unit_dir: Path, binary: str, _environ: Any) -> GeneratorCheck:
            seen["files"] = _tree(unit_dir)
            seen["dropin"] = (unit_dir / "mosquitto.container.d" / "50-margot-parameters.conf").read_text(encoding="utf-8")
            seen["binary"] = binary
            return GeneratorCheck(passed=True, detail="")

        install_host.generator.side_effect = capture

        _prepare(tmp_path).cleanup()

        assert seen["binary"] == "/usr/libexec/podman/quadlet"
        assert "mosquitto.container" in seen["files"]
        assert "conf/mosquitto.conf" in seen["files"]
        assert "mosquitto.container.d/50-margot-parameters.conf" in seen["files"]
        assert f'Environment="QUADLET_DIR={install_host.root / APP}"' in seen["dropin"]

    def test_a_failing_generator_is_exit_3_and_nothing_is_written(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should refuse with the trimmed generator output and never touch the host."""
        install_host.generator.return_value = GeneratorCheck(
            passed=False, detail="mosquitto.container: unknown key 'Imag'\nprocessing encountered some errors"
        )
        run = _systemctl(mocker)

        with raises(ValueError, match=r"unknown key 'Imag'") as info:
            _prepare(tmp_path)

        assert "nothing was written" in str(info.value).lower()
        assert not install_host.root.exists()
        run.assert_not_called()

    def test_a_missing_generator_warns_once_and_the_install_proceeds(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should add exactly one warning, skip the generator check, and still allow the install."""
        install_host.binary.return_value = None
        _systemctl(mocker)

        prepared = _prepare(tmp_path)
        try:
            install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        assert len(prepared.warnings) == 1
        assert "quadlet" in prepared.warnings[0].lower()
        install_host.generator.assert_not_called()
        assert (install_host.root / APP / "mosquitto.container").is_file()

    def test_a_present_generator_adds_no_warning(self, tmp_path: Path, install_host: Any) -> None:
        """Should produce no warning when the generator runs."""
        prepared = _prepare(tmp_path)
        try:
            assert prepared.warnings == ()
        finally:
            prepared.cleanup()


class TestPostReloadVerification:
    """Guard 3: after daemon-reload each expected service must be known to systemd."""

    def test_known_services_pass_and_only_show_reload_and_cat_are_called(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should run show-environment, daemon-reload and one cat per service, and nothing else."""
        run = _systemctl(mocker)
        prepared = _prepare(tmp_path)
        try:
            install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        verbs = [call.args[0][2] for call in run.call_args_list]
        assert verbs == ["show-environment", "daemon-reload", "cat"]
        assert run.call_args_list[-1].args[0][3] == "mosquitto.service"

    def test_missing_service_is_exit_1_with_the_hint_and_files_kept(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should name the service, the unit file and the diagnostics, and keep what was written."""
        _systemctl(mocker, missing=frozenset({"mosquitto.service"}))
        prepared = _prepare(tmp_path)
        try:
            with raises(SystemdError) as info:
                install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        message = str(info.value)
        assert "mosquitto.service" in message
        assert str(install_host.root / APP / "mosquitto.container") in message
        assert "/usr/libexec/podman/quadlet -dryrun -user" in message
        assert "journalctl --user -b -t quadlet-generator" in message
        assert "nothing was rolled back" in message.lower()
        assert (install_host.root / APP / "mosquitto.container").is_file()
        marker = json.loads((install_host.root / APP / MARKER_FILENAME).read_text(encoding="utf-8"))
        assert marker["state"] == "installed"

    def test_dry_run_calls_no_systemctl_and_writes_nothing(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should prepare and stop: no systemctl call of any kind, no file under the Quadlet root."""
        run = _systemctl(mocker)

        prepared = _prepare(tmp_path)
        prepared.cleanup()

        run.assert_not_called()
        assert not install_host.root.exists()
