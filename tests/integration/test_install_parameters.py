"""Integration tests for parameters as unit environment (sprint-13 §3.9): drop-ins written by apply_install,
the marker that holds parameter names only, upgrade cleanup, and the refusals of prepare_install.

systemctl is mocked and the Quadlet root is a tmp_path. Nothing touches the real user session.
"""

import json
from pathlib import Path
import stat
from typing import Any

from pytest import fixture, raises

from margot.domain.install import MARKER_FILENAME
from margot.services import install as install_service
from margot.services.install import InstallResult
from tests.integration._install_helpers import MOSQUITTO_CONTAINER, app_description, build_project, unquote_environment

APP = "com-belden-mosquitto"
DROPIN = "mosquitto.container.d/50-margot-parameters.conf"
MQTT_PARAMETER = """parameters:
  mqttPort:
    value: 1883
    targets:
      - pointer: MQTT_PORT
        components:
          - mosquitto-quadlet
"""
NO_VALUE_PARAMETER = """parameters:
  mqttPort:
    targets:
      - pointer: MQTT_PORT
        components:
          - mosquitto-quadlet
"""


@fixture
def systemctl(mocker: Any) -> Any:
    """Every systemctl --user call succeeds."""
    mocker.patch("margot.infra.systemd.which", return_value="/usr/bin/systemctl")
    return mocker.patch(
        "margot.infra.systemd.run",
        return_value=type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )


@fixture
def xdg(tmp_path: Path, monkeypatch: Any) -> Path:
    """The Quadlet root for this test."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "containers" / "systemd"


def _install(  # noqa: PLR0913 - keyword-only test builder
    tmp_path: Path,
    xdg: Path,
    *,
    run: str = "run",
    parameters: str = "",
    overrides: dict[str, str] | None = None,
    members: dict[str, bytes] | None = None,
) -> InstallResult:
    """Build a project with the given descriptor parameters and install it."""
    project, build = build_project(
        tmp_path / run,
        descriptor=app_description(parameters=parameters),
        archive_members=members,
    )
    prepared = install_service.prepare_install(
        uri=None,
        project_dir=str(project),
        build_dir=str(build),
        profile_id=None,
        overrides=overrides,
    )
    try:
        return install_service.apply_install(prepared, root=xdg)
    finally:
        prepared.cleanup()


def _marker(xdg: Path) -> dict[str, Any]:
    return json.loads((xdg / APP / MARKER_FILENAME).read_text(encoding="utf-8"))


def _environment_lines(xdg: Path) -> list[str]:
    """The Environment= lines of the mosquitto drop-in, in file order."""
    text = (xdg / APP / DROPIN).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.startswith("Environment=")]


class TestDropInPlacement:
    """The drop-in beside each unit, its content, its mode, and what the marker records."""

    def test_descriptor_default_is_written_beside_the_unit(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should write Environment=MQTT_PORT with the descriptor default under <unit>.d/ beside the unit."""
        _install(tmp_path, xdg, parameters=MQTT_PARAMETER)

        text = (xdg / APP / DROPIN).read_text(encoding="utf-8")
        assert text.endswith('[Service]\nEnvironment="MQTT_PORT=1883"\nEnvironment="QUADLET_DIR=' + f'{xdg / APP}"\n')

    def test_set_value_replaces_the_descriptor_default(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should write the --set value instead of the descriptor default."""
        _install(tmp_path, xdg, parameters=MQTT_PARAMETER, overrides={"mqttPort": "1884"})

        assert 'Environment="MQTT_PORT=1884"' in (xdg / APP / DROPIN).read_text(encoding="utf-8")

    def test_dropin_mode_is_0600(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should create the drop-in with mode 0600 because it may carry secrets."""
        _install(tmp_path, xdg, parameters=MQTT_PARAMETER)

        assert stat.S_IMODE((xdg / APP / DROPIN).stat().st_mode) == 0o600

    def test_every_unit_of_the_component_gets_a_dropin(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should write a drop-in beside each unit file of the target component."""
        members = {
            "mosquitto-1.0.2_mosquitto-quadlet/mosquitto.container": MOSQUITTO_CONTAINER,
            "mosquitto-1.0.2_mosquitto-quadlet/net.network": b"[Network]\nSubnet=10.89.0.0/24\n",
        }
        _install(tmp_path, xdg, parameters=MQTT_PARAMETER, members=members)

        assert (xdg / APP / "net.network.d" / "50-margot-parameters.conf").is_file()
        assert (xdg / APP / DROPIN).is_file()

    def test_marker_lists_the_dropin_and_only_parameter_names(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should record the drop-in in the component files and the parameter name, never the value."""
        _install(tmp_path, xdg, parameters=MQTT_PARAMETER, overrides={"mqttPort": "s3cr3t-value"})

        marker = _marker(xdg)
        assert marker["parameters"] == ["mqttPort"]
        assert DROPIN in marker["components"][0]["files"]
        assert "s3cr3t-value" not in (xdg / APP / MARKER_FILENAME).read_text(encoding="utf-8")
        assert "s3cr3t-value" in (xdg / APP / DROPIN).read_text(encoding="utf-8")

    def test_parameter_without_value_leaves_only_quadlet_dir_in_the_dropin(
        self, tmp_path: Path, systemctl: Any, xdg: Path
    ) -> None:
        """Should not apply a parameter without a value: the drop-in holds only QUADLET_DIR, and the marker names no parameter."""
        _install(tmp_path, xdg, parameters=NO_VALUE_PARAMETER)

        assert _environment_lines(xdg) == [f'Environment="QUADLET_DIR={xdg / APP}"']
        assert _marker(xdg)["parameters"] == []

    def test_parameter_for_another_component_is_ignored(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should neither apply nor report a parameter whose target names no component of this profile."""
        parameters = MQTT_PARAMETER.replace("mosquitto-quadlet", "other-component")
        project, build = build_project(tmp_path / "other", descriptor=app_description(parameters=parameters))
        prepared = install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)
        try:
            assert prepared.plan.unapplied == ()
            assert prepared.plan.parameters == ()
        finally:
            prepared.cleanup()


class TestQuadletDir:
    """margot always provides QUADLET_DIR, with or without descriptor parameters (sprint-13 §3.9)."""

    def test_unit_without_parameters_gets_a_dropin_with_only_quadlet_dir(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should write the drop-in with the header and the application directory when no parameter exists."""
        _install(tmp_path, xdg)

        text = (xdg / APP / DROPIN).read_text(encoding="utf-8")
        assert text.endswith(f'[Service]\nEnvironment="QUADLET_DIR={xdg / APP}"\n')
        assert stat.S_IMODE((xdg / APP / DROPIN).stat().st_mode) == 0o600
        assert _marker(xdg)["parameters"] == []
        assert DROPIN in _marker(xdg)["components"][0]["files"]

    def test_quadlet_dir_sorts_with_the_descriptor_variables(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should write QUADLET_DIR in name order next to MQTT_PORT, in one drop-in."""
        _install(tmp_path, xdg, parameters=MQTT_PARAMETER)

        assert _environment_lines(xdg) == [
            'Environment="MQTT_PORT=1883"',
            f'Environment="QUADLET_DIR={xdg / APP}"',
        ]

    def test_quadlet_dir_round_trips_byte_exactly_for_a_special_directory(
        self, tmp_path: Path, systemctl: Any, monkeypatch: Any
    ) -> None:
        """Should store the exact application directory when it has a space, %, quotes and non-ASCII."""
        base = tmp_path / 'cfg 100% "é" 中'
        monkeypatch.setenv("XDG_CONFIG_HOME", str(base))
        root = base / "containers" / "systemd"
        _install(tmp_path, root, parameters=MQTT_PARAMETER)

        line = _environment_lines(root)[1]
        assert line.startswith('Environment="QUADLET_DIR=')
        assert unquote_environment(line) == str(root / APP)

    def test_quadlet_dir_is_not_listed_as_a_parameter(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should keep the marker parameters to descriptor names: QUADLET_DIR is not a parameter."""
        _install(tmp_path, xdg, parameters=MQTT_PARAMETER)

        assert _marker(xdg)["parameters"] == ["mqttPort"]

    def test_user_dropin_can_override_quadlet_dir(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should keep a later user drop-in that sets QUADLET_DIR differently; margot does not rewrite it."""
        _install(tmp_path, xdg, run="a")
        local = xdg / APP / "mosquitto.container.d" / "90-local.conf"
        local.write_text('[Service]\nEnvironment="QUADLET_DIR=/srv/mosquitto"\n', encoding="utf-8")

        _install(tmp_path, xdg, run="b")

        assert local.read_text(encoding="utf-8") == '[Service]\nEnvironment="QUADLET_DIR=/srv/mosquitto"\n'
        assert f'Environment="QUADLET_DIR={xdg / APP}"' in (xdg / APP / DROPIN).read_text(encoding="utf-8")


class TestUpgradeOfDropIns:
    """Re-running install regenerates margot's drop-ins and never touches the user's."""

    def test_dropin_of_a_unit_no_longer_shipped_is_removed(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should delete the drop-in of a unit the previous marker listed and the new payload no longer ships."""
        net = {
            "mosquitto-1.0.2_mosquitto-quadlet/mosquitto.container": MOSQUITTO_CONTAINER,
            "mosquitto-1.0.2_mosquitto-quadlet/net.network": b"[Network]\nSubnet=10.89.0.0/24\n",
        }
        _install(tmp_path, xdg, run="a", parameters=MQTT_PARAMETER, members=net)
        _install(tmp_path, xdg, run="b", parameters=MQTT_PARAMETER)

        assert not (xdg / APP / "net.network.d").exists()
        assert 'Environment="MQTT_PORT=1883"' in (xdg / APP / DROPIN).read_text(encoding="utf-8")

    def test_reinstall_without_set_restores_the_descriptor_default(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should regenerate the drop-in with the descriptor default once --set is no longer given."""
        _install(tmp_path, xdg, run="a", parameters=MQTT_PARAMETER, overrides={"mqttPort": "1884"})
        _install(tmp_path, xdg, run="b", parameters=MQTT_PARAMETER)

        assert 'Environment="MQTT_PORT=1883"' in (xdg / APP / DROPIN).read_text(encoding="utf-8")

    def test_user_dropin_beside_the_unit_survives_an_upgrade(self, tmp_path: Path, systemctl: Any, xdg: Path) -> None:
        """Should keep a hand-written 90-local.conf that margot did not write, and leave it to override margot's."""
        _install(tmp_path, xdg, run="a", parameters=MQTT_PARAMETER)
        local = xdg / APP / "mosquitto.container.d" / "90-local.conf"
        local.write_text('[Service]\nEnvironment="MQTT_PORT=1999"\n', encoding="utf-8")

        _install(tmp_path, xdg, run="b", parameters=MQTT_PARAMETER, overrides={"mqttPort": "1884"})

        assert local.read_text(encoding="utf-8") == '[Service]\nEnvironment="MQTT_PORT=1999"\n'
        assert 'Environment="MQTT_PORT=1884"' in (xdg / APP / DROPIN).read_text(encoding="utf-8")


class TestRefusals:
    """Parameter problems are refused while the plan is prepared, before the host is touched."""

    def _prepare(self, tmp_path: Path, parameters: str, overrides: dict[str, str] | None = None) -> None:
        project, build = build_project(tmp_path, descriptor=app_description(parameters=parameters))
        prepared = install_service.prepare_install(
            uri=None,
            project_dir=str(project),
            build_dir=str(build),
            profile_id=None,
            overrides=overrides,
        )
        prepared.cleanup()

    def test_array_value_is_refused(self, tmp_path: Path) -> None:
        """Should refuse an array descriptor value that would be applied, naming the parameter."""
        parameters = MQTT_PARAMETER.replace("value: 1883", "value:\n      - a\n      - b")
        with raises(ValueError, match=r"'mqttPort'.*array"):
            self._prepare(tmp_path, parameters)

    def test_unknown_set_name_is_refused(self, tmp_path: Path) -> None:
        """Should refuse --set for a name that is not an applicable parameter."""
        with raises(ValueError, match=r"not a parameter of this profile"):
            self._prepare(tmp_path, MQTT_PARAMETER, overrides={"ghost": "1"})

    def test_newline_in_set_value_is_refused(self, tmp_path: Path) -> None:
        """Should refuse a --set value with a newline, naming the parameter."""
        with raises(ValueError, match=r"'mqttPort'.*newline"):
            self._prepare(tmp_path, MQTT_PARAMETER, overrides={"mqttPort": "a\nb"})

    def test_two_parameters_on_one_pointer_are_refused(self, tmp_path: Path) -> None:
        """Should refuse two parameters that set MQTT_PORT on the same component, naming both."""
        parameters = MQTT_PARAMETER + (
            "  mqttPortAgain:\n    value: 1\n    targets:\n      - pointer: MQTT_PORT\n        components:\n"
            "          - mosquitto-quadlet\n"
        )
        with raises(ValueError, match=r"'mqttPort' and 'mqttPortAgain'"):
            self._prepare(tmp_path, parameters)

    def test_quadlet_dir_pointer_is_refused(self, tmp_path: Path) -> None:
        """Should refuse a descriptor parameter that uses QUADLET_DIR as its pointer, naming it as reserved."""
        parameters = MQTT_PARAMETER.replace("MQTT_PORT", "QUADLET_DIR")
        with raises(ValueError, match=r"'mqttPort'.*QUADLET_DIR.*reserved by margot"):
            self._prepare(tmp_path, parameters)

    def test_invalid_pointer_is_refused(self, tmp_path: Path) -> None:
        """Should refuse a pointer that is not an environment variable name."""
        parameters = MQTT_PARAMETER.replace("MQTT_PORT", "MQTT-PORT")
        with raises(ValueError, match=r"'mqttPort'.*MQTT-PORT"):
            self._prepare(tmp_path, parameters)
