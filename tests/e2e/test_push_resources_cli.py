"""E2E tests: resource files referenced by app.yaml are pushed with the right media type via the CLI.

Runs the real `margot build` and `margot push` with the default relative build directory (.dist).
Only the registry boundary is faked: OrasClient._push_artifact (the method that uploads blobs and
the manifest) and the credential check. Everything else, including resource discovery in
push_margo, runs for real and the file entries passed to _push_artifact are asserted.
"""

from pathlib import Path
import re
from typing import Any

from pytest import MonkeyPatch, fixture
from typer.testing import CliRunner

from margot.domain.layers import (
    MARGO_DESCRIPTION_MEDIA_TYPE,
    MARGO_ICON_MEDIA_TYPE_TEMPLATE,
    MARGO_RESOURCE_ANNOTATION,
    MARGO_RESOURCE_ANNOTATION_VALUE,
)
from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

PUSH_ARGS = ["push", "--type", "margo", "--registry", "public.ecr.aws", "--repository", "g2n4p2m7/margo"]

MARGO_YAML = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
"""

# The icon is an SVG with a non-png extension, so it is not one of the four names the old push
# code knew about. licenseFile points at a file that does not exist to exercise the missing-file path.
APP_YAML = """\
apiVersion: application.margo.org/v1alpha1
kind: ApplicationDescription
id: testapp
metadata:
  name: testapp
  version: 1.0.0
  catalog:
    application:
      icon: resources/icon.svg
      licenseFile: resources/missing-license.txt
"""


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


@fixture
def svg_project(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Create a margo project whose app.yaml references an SVG icon, then cd into it."""
    (tmp_path / "margo.yaml").write_text(MARGO_YAML, encoding="utf-8")
    source = tmp_path / "margo"
    (source / "resources").mkdir(parents=True)
    (source / "app.yaml").write_text(APP_YAML, encoding="utf-8")
    (source / "resources" / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _build_and_push(mocker: Any) -> tuple[Any, Any]:
    """Run the real build, then the real push with the registry boundary faked.

    Returns:
        (push_result, upload_mock). upload_mock.call_args.kwargs["file_entries"] holds the layers.
    """
    build_result = runner.invoke(app, ["build", "--type", "margo"])
    assert build_result.exit_code == 0, _strip_ansi(build_result.stdout + (build_result.stderr or ""))

    mocker.patch("margot.services.push.credentials.check_credentials")
    upload_mock = mocker.patch("margot.infra.oci.OrasClient._push_artifact")
    push_result = runner.invoke(app, PUSH_ARGS)
    return push_result, upload_mock


class TestPushSvgIconCLI:
    """The SVG icon from the originally reported bug is shipped under its real media type."""

    def test_svg_icon_layer_has_typed_media_type_title_and_resource_annotation(
        self, svg_project: Path, mocker: Any
    ) -> None:
        """Should push the referenced SVG once with icon.v1+svg, its title, and org.margo.app.resource."""
        result, upload_mock = _build_and_push(mocker)

        assert result.exit_code == 0, _strip_ansi(result.stdout + (result.stderr or ""))
        upload_mock.assert_called_once()
        file_entries = upload_mock.call_args.kwargs["file_entries"]

        icon_entries = [entry for entry in file_entries if entry[2] == "resources/icon.svg"]
        assert len(icon_entries) == 1
        _, media_type, title, annotations = icon_entries[0]
        assert media_type == MARGO_ICON_MEDIA_TYPE_TEMPLATE.format(ext="svg")
        assert media_type == "application/vnd.margo.app.icon.v1+svg"
        assert title == "resources/icon.svg"
        assert annotations == {MARGO_RESOURCE_ANNOTATION: MARGO_RESOURCE_ANNOTATION_VALUE}

    def test_descriptor_layer_is_first_and_carries_no_resource_annotation(
        self, svg_project: Path, mocker: Any
    ) -> None:
        """Should push app.yaml as the first layer, typed as the descriptor, without org.margo.app.resource."""
        result, upload_mock = _build_and_push(mocker)

        assert result.exit_code == 0
        file_entries = upload_mock.call_args.kwargs["file_entries"]
        descriptor_entry = file_entries[0]
        assert descriptor_entry[1] == MARGO_DESCRIPTION_MEDIA_TYPE
        assert descriptor_entry[2] == "app.yaml"
        assert len(descriptor_entry) == 3

    def test_missing_referenced_license_warns_and_push_still_exits_0(self, svg_project: Path, mocker: Any) -> None:
        """Should warn that the referenced licenseFile is missing, skip it, and exit 0."""
        result, upload_mock = _build_and_push(mocker)

        plain = _strip_ansi(result.stdout + (result.stderr or ""))
        assert result.exit_code == 0, plain
        assert "'licenseFile' references 'resources/missing-license.txt' but the file was not found; skipping." in plain
        titles = [entry[2] for entry in upload_mock.call_args.kwargs["file_entries"]]
        assert "resources/missing-license.txt" not in titles
