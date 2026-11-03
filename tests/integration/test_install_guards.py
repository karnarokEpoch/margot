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
from margot.infra.systemd import GeneratorRun, SystemdError
from margot.services import install as install_service
from tests.integration._install_helpers import answer_by_run, build_project, quadlet_payload

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

        def capture(unit_dir: Path, binary: str, _environ: Any) -> GeneratorRun:
            seen["files"] = _tree(unit_dir)
            seen["dropin"] = (unit_dir / "mosquitto.container.d" / "50-margot-parameters.conf").read_text(encoding="utf-8")
            seen["binary"] = binary
            return GeneratorRun(returncode=0, stderr="")

        install_host.generator.side_effect = capture

        _prepare(tmp_path).cleanup()

        assert seen["binary"] == "/usr/libexec/podman/quadlet"
        assert "mosquitto.container" in seen["files"]
        assert "conf/mosquitto.conf" in seen["files"]
        assert "mosquitto.container.d/50-margot-parameters.conf" in seen["files"]
        assert f'Environment="QUADLET_DIR={install_host.root / APP}"' in seen["dropin"]

    def test_a_failing_generator_is_exit_3_and_nothing_is_written(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should refuse with the trimmed generator output and never touch the host."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1,
            stderr=(
                "quadlet-generator[1]: converting \"mosquitto.container\": unsupported key 'Imag' in group 'Container'\n"
                "quadlet-generator[1]: processing encountered some errors"
            ),
        )
        run = _systemctl(mocker)

        with raises(ValueError, match=r"unsupported key 'Imag'") as info:
            _prepare(tmp_path)

        assert "nothing was written" in str(info.value).lower()
        assert "processing encountered" not in str(info.value)
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


NETWORK_UNIT = b"[Container]\nImage=docker.io/library/eclipse-mosquitto:2\nNetwork=owner.network\n"
VOLUME_UNIT = b"[Container]\nImage=docker.io/library/eclipse-mosquitto:2\nVolume=owner.volume:/data\n"
PAYLOAD_DIR = "mosquitto-1.0.2_mosquitto-quadlet"


def _members(units: dict[str, bytes]) -> dict[str, bytes]:
    """The quadlet payload with extra or replaced unit files (file name -> content)."""
    members = quadlet_payload()
    for name, data in units.items():
        members[f"{PAYLOAD_DIR}/{name}"] = data
    return members


def _generator_lines(*references: tuple[str, str], errors: tuple[str, ...] = ()) -> str:
    """Generator stderr as the host prints it: progress lines, one line per reference, then real errors."""
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


def _prepare_members(tmp_path: Path, members: dict[str, bytes]) -> Any:
    project, build = build_project(tmp_path, archive_members=members)
    return install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)


class TestUnresolvedReferences:
    """A unit may refer to another unit that is not in the application (sprint-13 §3.10, principle).

    The generator sees only the staged tree, so such a reference is reported as unresolved. The
    install checks the host: a unit already installed is silent; a missing one is one warning and its
    service is not required to exist yet (guard 3).
    """

    def test_reference_to_a_unit_on_the_host_is_silent_and_the_service_is_checked(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should install with no warning when the referenced network already exists elsewhere in the search path."""
        _unit(install_host.root, "handmade", "owner.network", "[Network]\n")
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.network"))
        )
        run = _systemctl(mocker)
        prepared = _prepare_members(tmp_path, _members({"mosquitto.container": NETWORK_UNIT}))
        try:
            install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        assert prepared.warnings == ()
        assert prepared.deferred == ()
        assert (install_host.root / APP / "mosquitto.container").is_file()
        assert ["cat", "mosquitto.service"] in [call.args[0][2:] for call in run.call_args_list]

    def test_reference_to_a_unit_of_the_own_directory_is_silent(self, tmp_path: Path, install_host: Any) -> None:
        """Should accept a reference to a unit the application already has in its own directory (an upgrade)."""
        _unit(install_host.root, APP, "owner.network", "[Network]\n")
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.network"))
        )

        prepared = _prepare_members(tmp_path, _members({"mosquitto.container": NETWORK_UNIT}))
        try:
            assert prepared.warnings == ()
            assert prepared.deferred == ()
        finally:
            prepared.cleanup()

    def test_reference_to_a_missing_unit_warns_once_and_defers_its_service(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should add one warning naming the unit file and the missing unit, and defer that service."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.network"))
        )

        prepared = _prepare_members(tmp_path, _members({"mosquitto.container": NETWORK_UNIT}))
        try:
            assert prepared.warnings == (
                "mosquitto.container references owner.network, which is not installed on this host. "
                "mosquitto.service is generated once owner.network is installed and systemd is reloaded.",
            )
            assert prepared.deferred == ("mosquitto.service",)
        finally:
            prepared.cleanup()

    def test_deferred_service_is_not_checked_after_reload(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should not require the deferred service to be known, and never call systemctl cat for it."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.network"))
        )
        run = _systemctl(mocker, missing=frozenset({"mosquitto.service"}))
        prepared = _prepare_members(tmp_path, _members({"mosquitto.container": NETWORK_UNIT}))
        try:
            result = install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        assert result.services == ()
        assert result.start_services == ()
        assert [call.args[0][2:] for call in run.call_args_list] == [["show-environment"], ["daemon-reload"]]
        assert (install_host.root / APP / "mosquitto.container").is_file()

    def test_each_missing_reference_is_one_warning_in_unit_order(self, tmp_path: Path, install_host: Any) -> None:
        """Should warn once per unit and missing unit, in the order the units are installed."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1,
            stderr=_generator_lines(("mosquitto.container", "owner.network"), ("other.container", "owner.volume")),
        )
        members = _members({"mosquitto.container": NETWORK_UNIT, "other.container": VOLUME_UNIT})

        prepared = _prepare_members(tmp_path, members)
        try:
            assert [message.split(",")[0] for message in prepared.warnings] == [
                "mosquitto.container references owner.network",
                "other.container references owner.volume",
            ]
            assert prepared.deferred == ("mosquitto.service", "other.service")
        finally:
            prepared.cleanup()

    def test_a_real_error_next_to_a_reference_fails_and_lists_only_the_error(self, tmp_path: Path, install_host: Any) -> None:
        """Should refuse with exit 3 and show only the real error line, not the reference."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1,
            stderr=_generator_lines(
                ("mosquitto.container", "owner.network"),
                errors=("quadlet-generator[1]: converting \"other.container\": unsupported key 'NoSuchKey'",),
            ),
        )

        with raises(ValueError, match=r"NoSuchKey") as info:
            _prepare_members(tmp_path, _members({"mosquitto.container": NETWORK_UNIT}))

        message = str(info.value)
        assert "owner.network was not found" not in message
        assert "Loading source" not in message
        assert not install_host.root.exists()

    def test_a_unit_may_reference_an_existing_external_network(self, tmp_path: Path, install_host: Any) -> None:
        """Contrast with guard 1: a unit that references an external network installs fine."""
        _unit(install_host.root, "handmade", "owner.network", "[Network]\n")
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.network"))
        )

        prepared = _prepare_members(tmp_path, _members({"mosquitto.container": NETWORK_UNIT}))
        try:
            assert prepared.warnings == ()
        finally:
            prepared.cleanup()

    def test_a_unit_that_ships_an_existing_network_name_is_refused(self, tmp_path: Path, install_host: Any) -> None:
        """Contrast with the reference case: shipping a file named owner.network shadows it, so it is refused."""
        _unit(install_host.root, "handmade", "owner.network", "[Network]\n")

        with raises(ValueError, match=r"same file name owner\.network"):
            _prepare_members(tmp_path, _members({"owner.network": b"[Network]\nSubnet=10.9.0.0/24\n"}))


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


class TestDeferredVerification:
    """Guard 3 keeps checking every service that is not deferred by an unresolved reference."""

    def test_a_missing_service_that_is_not_deferred_is_still_an_error(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should fail with the service name when a non-deferred service is unknown after reload (exit 1)."""
        install_host.generator.return_value = GeneratorRun(
            returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.network"))
        )
        _systemctl(mocker, missing=frozenset({"other.service"}))
        members = _members({"mosquitto.container": NETWORK_UNIT, "other.container": b"[Container]\nImage=x\n"})
        prepared = _prepare_members(tmp_path, members)
        try:
            with raises(SystemdError) as info:
                install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        message = str(info.value)
        assert "other.service" in message
        assert "mosquitto.service" not in message


F_UNIT = b"[Container]\nImage=docker.io/library/eclipse-mosquitto:2\nNetwork=owner.network\nVolume=owner.volume:/data\n"
VOLUME_WARNING = (
    "mosquitto.container references owner.volume, which is not installed on this host. "
    "mosquitto.service is generated once owner.volume is installed and systemd is reloaded."
)


def _host_runs(generator: Any) -> list[Any]:
    """The calls of check_units that used the real search path (unit directory None)."""
    return [call for call in generator.call_args_list if call.args[0] is None]


class TestMissingServiceAfterReload:
    """Guard 3 asks the host generator why a service is unknown after reload (sprint-13 §3.10, principle).

    The staged dry run reports only the first unresolved reference of a unit, so a unit with a second
    missing reference passes guard 2 and is absent after reload. The host run, with the real search path,
    names the reference. A reference-only diagnosis is a warning; anything else is exit 1.
    """

    def test_a_missing_second_reference_is_a_warning_and_the_install_succeeds(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should write the files, return one warning for the missing volume and not require the service."""
        _unit(install_host.root, "handmade", "owner.network", "[Network]\n")
        install_host.generator.side_effect = answer_by_run(
            staged=GeneratorRun(returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.network"))),
            host=GeneratorRun(returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.volume"))),
        )
        _systemctl(mocker, missing=frozenset({"mosquitto.service"}))
        prepared = _prepare_members(tmp_path, _members({"mosquitto.container": F_UNIT}))
        try:
            result = install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        assert prepared.warnings == ()
        assert result.warnings == (VOLUME_WARNING,)
        assert result.services == ()
        assert result.start_services == ()
        assert (install_host.root / APP / "mosquitto.container").is_file()
        assert len(_host_runs(install_host.generator)) == 1

    def test_a_real_error_behind_the_reference_is_exit_1_after_the_write(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should refuse with the error line of that unit and keep the written files."""
        error = "quadlet-generator[1]: converting \"mosquitto.container\": unsupported key 'NoSuchKey' in group 'Container'"
        install_host.generator.side_effect = answer_by_run(
            staged=GeneratorRun(returncode=0, stderr=""),
            host=GeneratorRun(returncode=1, stderr=_generator_lines(("mosquitto.container", "owner.volume"), errors=(error,))),
        )
        _systemctl(mocker, missing=frozenset({"mosquitto.service"}))
        prepared = _prepare_members(tmp_path, _members({"mosquitto.container": F_UNIT}))
        try:
            with raises(SystemdError) as info:
                install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        message = str(info.value)
        assert "NoSuchKey" in message
        assert "owner.volume" not in message
        assert "nothing was rolled back" in message.lower()
        assert (install_host.root / APP / "mosquitto.container").is_file()

    def test_a_missing_service_with_no_generator_line_is_exit_1(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should fail when the host generator says nothing about the missing unit."""
        install_host.generator.side_effect = answer_by_run(
            staged=GeneratorRun(returncode=0, stderr=""), host=GeneratorRun(returncode=0, stderr="")
        )
        _systemctl(mocker, missing=frozenset({"mosquitto.service"}))
        prepared = _prepare(tmp_path)
        try:
            with raises(SystemdError, match=r"systemd does not know mosquitto\.service"):
                install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

    def test_a_missing_generator_binary_is_exit_1_and_no_host_run_is_made(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should fail, with the usual message, when the generator cannot be found for the diagnosis."""
        install_host.binary.return_value = None
        _systemctl(mocker, missing=frozenset({"mosquitto.service"}))
        prepared = _prepare(tmp_path)
        try:
            with raises(SystemdError, match=r"systemd does not know mosquitto\.service"):
                install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        assert _host_runs(install_host.generator) == []

    def test_a_host_run_that_cannot_be_done_is_exit_1(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should fail with the usual message when the diagnosing run itself fails."""
        install_host.generator.side_effect = answer_by_run(
            staged=GeneratorRun(returncode=0, stderr=""),
            host=SystemdError("The Quadlet generator could not run: Exec format error"),
        )
        _systemctl(mocker, missing=frozenset({"mosquitto.service"}))
        prepared = _prepare(tmp_path)
        try:
            with raises(SystemdError, match=r"systemd does not know mosquitto\.service") as info:
                install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        assert "nothing was rolled back" in str(info.value).lower()

    def test_two_missing_services_are_diagnosed_in_one_host_run(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should run the host generator once for all missing services and warn for each, in unit order."""
        install_host.generator.side_effect = answer_by_run(
            staged=GeneratorRun(returncode=0, stderr=""),
            host=GeneratorRun(
                returncode=1,
                stderr=_generator_lines(("mosquitto.container", "owner.volume"), ("other.container", "owner.network")),
            ),
        )
        _systemctl(mocker, missing=frozenset({"mosquitto.service", "other.service"}))
        members = _members({"mosquitto.container": F_UNIT, "other.container": NETWORK_UNIT})
        prepared = _prepare_members(tmp_path, members)
        try:
            result = install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        assert len(_host_runs(install_host.generator)) == 1
        assert result.warnings == (
            VOLUME_WARNING,
            "other.container references owner.network, which is not installed on this host. "
            "other.service is generated once owner.network is installed and systemd is reloaded.",
        )

    def test_happy_path_runs_no_host_run_and_issues_the_expected_systemctl_calls(
        self, tmp_path: Path, install_host: Any, mocker: Any
    ) -> None:
        """Should make one generator run (the staged tree) and exactly show-environment, daemon-reload and cat."""
        run = _systemctl(mocker)
        prepared = _prepare(tmp_path)
        try:
            result = install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        assert len(install_host.generator.call_args_list) == 1
        assert install_host.generator.call_args.args[0] is not None
        assert [call.args[0][2:] for call in run.call_args_list] == [
            ["show-environment"],
            ["daemon-reload"],
            ["cat", "mosquitto.service"],
        ]
        assert result.warnings == ()
        assert result.services == ("mosquitto.service",)


class TestMissingServiceMessage:
    """The exit-1 message keeps the generator lines short."""

    def test_a_long_generator_error_is_trimmed_in_the_message(self, tmp_path: Path, install_host: Any, mocker: Any) -> None:
        """Should trim a very long error line of the failing unit, so the message stays readable."""
        long_error = 'quadlet-generator[1]: converting "mosquitto.container": ' + "x" * 2000
        install_host.generator.side_effect = answer_by_run(
            staged=GeneratorRun(returncode=0, stderr=""),
            host=GeneratorRun(returncode=1, stderr=_generator_lines(errors=(long_error,))),
        )
        _systemctl(mocker, missing=frozenset({"mosquitto.service"}))
        prepared = _prepare(tmp_path)
        try:
            with raises(SystemdError) as info:
                install_service.apply_install(prepared, root=install_host.root)
        finally:
            prepared.cleanup()

        message = str(info.value)
        assert "x" * 500 in message
        assert "x" * 700 not in message
        assert "x..." in message
