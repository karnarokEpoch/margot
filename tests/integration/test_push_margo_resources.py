"""End-to-end regression: a real margo build pushed through the default relative build directory.

Guards the bug where resource references were read from the top level of app.yaml, so every
resource was pushed as application/octet-stream. References live at metadata.catalog.application.
"""

from pathlib import Path
from typing import Any

from pytest import MonkeyPatch, fixture

from margot.domain.layers import (
    MARGO_DESCRIPTION_FILE_MEDIA_TYPE_TEMPLATE,
    MARGO_DESCRIPTION_MEDIA_TYPE,
    MARGO_ICON_MEDIA_TYPE_TEMPLATE,
    MARGO_LICENSE_FILE_MEDIA_TYPE_TEMPLATE,
    MARGO_RELEASE_NOTES_MEDIA_TYPE_TEMPLATE,
    MARGO_RESOURCE_ANNOTATION,
    MARGO_RESOURCE_ANNOTATION_VALUE,
    MARGO_RESOURCE_FALLBACK_MEDIA_TYPE,
)
from margot.domain.models import PackageType
from margot.infra.oci import OrasClient
from margot.services import build

RESOURCE_ANNOTATIONS = {MARGO_RESOURCE_ANNOTATION: MARGO_RESOURCE_ANNOTATION_VALUE}

MARGO_YAML = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
"""

APP_YAML = """\
apiVersion: v1
metadata:
  name: testapp
  version: 1.0.0
  catalog:
    application:
      icon: ./resources/icon.png
      descriptionFile: resources/description.md
      licenseFile: resources/license.txt
      releaseNotes: ./resources/release-notes.md
"""


@fixture
def project(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Create a margo project with a nested app.yaml and resources, then cd into it.

    Building with the default relative build directory (.dist) requires the working directory
    to be the project root, so the test changes into tmp_path.
    """
    (tmp_path / "margo.yaml").write_text(MARGO_YAML)

    source = tmp_path / "margo"
    resources = source / "resources"
    (resources / "screenshots").mkdir(parents=True)
    (source / "app.yaml").write_text(APP_YAML)
    (resources / "icon.png").write_bytes(b"\x89PNG")
    (resources / "description.md").write_text("# Description")
    (resources / "license.txt").write_text("MIT")
    (resources / "release-notes.md").write_text("# Notes")
    (resources / "screenshots" / "a.png").write_bytes(b"\x89PNG")

    monkeypatch.chdir(tmp_path)
    return tmp_path


def _annotations(entry: tuple[Any, ...]) -> dict[str, str] | None:
    """Return the extra annotations of a file entry, or None for the descriptor entry."""
    return entry[3] if len(entry) == 4 else None


class TestPushMargoDefaultBuildDir:
    """Real build output pushed through push_margo with the default relative build directory."""

    def test_resources_get_typed_media_types_not_octet_stream(self, project: Path, mocker: Any) -> None:
        """Every referenced resource gets its typed media type, titled under resources/, exactly once."""
        build.build(PackageType.MARGO)
        assert (project / ".dist" / "1.0.0" / "margo" / "app.yaml").is_file()

        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        client = OrasClient()
        push = mocker.patch.object(client, "_push_artifact")
        console_mock = mocker.patch("margot.infra.oci.console")

        client.push_margo(
            build_dir=".dist",
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        file_entries = push.call_args.kwargs["file_entries"]
        summary = [(entry[2], entry[1], _annotations(entry)) for entry in file_entries]
        assert summary == [
            ("app.yaml", MARGO_DESCRIPTION_MEDIA_TYPE, None),
            (
                "resources/icon.png",
                MARGO_ICON_MEDIA_TYPE_TEMPLATE.format(ext="png"),
                RESOURCE_ANNOTATIONS,
            ),
            (
                "resources/description.md",
                MARGO_DESCRIPTION_FILE_MEDIA_TYPE_TEMPLATE.format(ext="markdown"),
                RESOURCE_ANNOTATIONS,
            ),
            (
                "resources/license.txt",
                MARGO_LICENSE_FILE_MEDIA_TYPE_TEMPLATE.format(ext="txt"),
                RESOURCE_ANNOTATIONS,
            ),
            (
                "resources/release-notes.md",
                MARGO_RELEASE_NOTES_MEDIA_TYPE_TEMPLATE.format(ext="markdown"),
                RESOURCE_ANNOTATIONS,
            ),
            (
                "resources/screenshots/a.png",
                MARGO_RESOURCE_FALLBACK_MEDIA_TYPE,
                RESOURCE_ANNOTATIONS,
            ),
        ]

        titles = [entry[2] for entry in file_entries]
        assert len(set(titles)) == len(titles)
        referenced_media_types = [entry[1] for entry in file_entries[1:5]]
        assert MARGO_RESOURCE_FALLBACK_MEDIA_TYPE not in referenced_media_types

        for entry in file_entries:
            assert Path(entry[0]).is_file()

        console_mock.warning.assert_not_called()
