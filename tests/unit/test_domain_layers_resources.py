"""Unit tests for domain/layers.py resource resolution."""

from pathlib import Path
from typing import Any

from pytest import MonkeyPatch, mark

from margot.domain.layers import (
    MARGO_RESOURCE_FALLBACK_MEDIA_TYPE,
    resolve_margo_resource_files,
)


def _write_resource(margo_dir: Path, relative: str, content: bytes = b"x") -> Path:
    """Create a resource file under margo_dir, creating parent folders as needed."""
    path = margo_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestResolveMargoResourceFiles:
    """Tests for resolve_margo_resource_files()."""

    def test_icon_svg_extension(self, tmp_path: Path) -> None:
        """SVG icon should resolve with svg extension in media type."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        icon_path = resources_dir / "icon.svg"
        icon_path.write_text("<svg></svg>")

        app_yaml = {"icon": "resources/icon.svg"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 1
        assert files[0].path == icon_path
        assert files[0].media_type == "application/vnd.margo.app.icon.v1+svg"
        assert files[0].title == "resources/icon.svg"
        assert missing == []

    def test_icon_no_extension_uses_bin_fallback(self, tmp_path: Path) -> None:
        """File with no extension should use 'bin' as the {file format} token."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        icon_path = resources_dir / "icon"
        icon_path.write_bytes(b"binary")

        app_yaml = {"icon": "resources/icon"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 1
        assert files[0].media_type == "application/vnd.margo.app.icon.v1+bin"
        assert missing == []

    def test_icon_uppercase_extension_lowercased(self, tmp_path: Path) -> None:
        """Uppercase extensions should be lowercased."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        icon_path = resources_dir / "icon.PNG"
        icon_path.write_bytes(b"\x89PNG")

        app_yaml = {"icon": "resources/icon.PNG"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 1
        assert files[0].media_type == "application/vnd.margo.app.icon.v1+png"
        assert missing == []

    @mark.parametrize(
        ("filename", "expected_token"),
        [
            ("icon.jpg", "jpeg"),
            ("icon.jpeg", "jpeg"),
            ("icon.JPG", "jpeg"),
            ("icon.tif", "tiff"),
            ("icon.tiff", "tiff"),
            ("icon.md", "markdown"),
            ("icon.markdown", "markdown"),
            ("icon.png", "png"),
            ("icon.svg", "svg"),
            ("icon.bmp", "bmp"),
            ("icon.txt", "txt"),
        ],
    )
    def test_file_format_token_table(self, tmp_path: Path, filename: str, expected_token: str) -> None:
        """Each extension maps through the {file format} table; unmapped ones pass through."""
        margo_dir = tmp_path / "margo"
        _write_resource(margo_dir, f"resources/{filename}")

        files, missing = resolve_margo_resource_files({"icon": f"resources/{filename}"}, margo_dir)

        assert len(files) == 1
        assert files[0].media_type == f"application/vnd.margo.app.icon.v1+{expected_token}"
        assert missing == []

    @mark.parametrize(
        ("field", "filename", "expected_media_type"),
        [
            ("icon", "icon.png", "application/vnd.margo.app.icon.v1+png"),
            ("licenseFile", "license.txt", "application/vnd.margo.app.licenseFile.v1+txt"),
            ("releaseNotes", "release-notes.md", "application/vnd.margo.app.releaseNotes.v1+markdown"),
            ("descriptionFile", "description.md", "application/vnd.margo.app.descriptionFile.v1+markdown"),
        ],
    )
    def test_original_four_filenames_regression(
        self, tmp_path: Path, field: str, filename: str, expected_media_type: str
    ) -> None:
        """The four filenames the old hardcoded list handled keep their media types."""
        margo_dir = tmp_path / "margo"
        _write_resource(margo_dir, f"resources/{filename}")

        files, missing = resolve_margo_resource_files({field: f"resources/{filename}"}, margo_dir)

        assert len(files) == 1
        assert files[0].media_type == expected_media_type
        assert files[0].title == f"resources/{filename}"
        assert missing == []

    def test_missing_referenced_file(self, tmp_path: Path) -> None:
        """Missing referenced file should be tracked in missing_fields."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()

        app_yaml = {"icon": "resources/icon.svg"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 0
        assert missing == ["icon"]

    def test_description_file_field(self, tmp_path: Path) -> None:
        """descriptionFile field should use the descriptionFile template with the markdown token."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        desc_path = resources_dir / "DESCRIPTION.md"
        desc_path.write_text("# Description")

        app_yaml = {"descriptionFile": "resources/DESCRIPTION.md"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 1
        assert files[0].media_type == "application/vnd.margo.app.descriptionFile.v1+markdown"
        assert missing == []

    def test_license_file_field(self, tmp_path: Path) -> None:
        """licenseFile field should use the licenseFile template (spec name) with the txt token."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        license_path = resources_dir / "LICENSE.txt"
        license_path.write_text("MIT License")

        app_yaml = {"licenseFile": "resources/LICENSE.txt"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 1
        assert files[0].media_type == "application/vnd.margo.app.licenseFile.v1+txt"
        assert missing == []

    def test_release_notes_field(self, tmp_path: Path) -> None:
        """releaseNotes field should use the releaseNotes template with the markdown token."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        notes_path = resources_dir / "RELEASE.md"
        notes_path.write_text("# Release Notes")

        app_yaml = {"releaseNotes": "resources/RELEASE.md"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 1
        assert files[0].media_type == "application/vnd.margo.app.releaseNotes.v1+markdown"
        assert missing == []

    def test_extra_resource_files_fallback(self, tmp_path: Path) -> None:
        """Extra files in resources/ not referenced by app.yaml should use fallback media type."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        # Create a file not referenced in app.yaml
        screenshot_path = resources_dir / "screenshot.png"
        screenshot_path.write_bytes(b"\x89PNG")

        app_yaml: dict[str, Any] = {}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 1
        assert files[0].path == screenshot_path
        assert files[0].media_type == MARGO_RESOURCE_FALLBACK_MEDIA_TYPE
        assert files[0].title == "resources/screenshot.png"
        assert missing == []

    def test_referenced_file_not_duplicated_in_scan(self, tmp_path: Path) -> None:
        """A file referenced in app.yaml should not be added again during resources/ scan."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        icon_path = resources_dir / "icon.png"
        icon_path.write_bytes(b"\x89PNG")

        app_yaml = {"icon": "resources/icon.png"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        # Should only appear once, with the icon media type, not the fallback
        assert len(files) == 1
        assert files[0].media_type == "application/vnd.margo.app.icon.v1+png"
        assert missing == []

    def test_referenced_icon_emitted_once_with_relative_margo_dir(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """A referenced icon should appear exactly once when margo_dir is a relative path (default .dist)."""
        monkeypatch.chdir(tmp_path)
        _write_resource(Path(".dist/1.0.0/margo"), "resources/icon.png", b"\x89PNG")

        files, missing = resolve_margo_resource_files(
            {"icon": "resources/icon.png"},
            Path(".dist/1.0.0/margo"),
        )

        assert [f.media_type for f in files] == ["application/vnd.margo.app.icon.v1+png"]
        assert files[0].title == "resources/icon.png"
        assert missing == []

    def test_referenced_icon_emitted_once_via_symlinked_margo_dir(self, tmp_path: Path) -> None:
        """A referenced icon should appear exactly once when margo_dir is reached through a symlink."""
        real_margo_dir = tmp_path / "real" / "margo"
        _write_resource(real_margo_dir, "resources/icon.png", b"\x89PNG")
        link_margo_dir = tmp_path / "link"
        link_margo_dir.symlink_to(real_margo_dir, target_is_directory=True)

        files, missing = resolve_margo_resource_files({"icon": "resources/icon.png"}, link_margo_dir)

        assert [f.media_type for f in files] == ["application/vnd.margo.app.icon.v1+png"]
        assert files[0].title == "resources/icon.png"
        assert missing == []

    def test_nested_extra_titles_keep_subfolder(self, tmp_path: Path) -> None:
        """Same-named files in different sub-folders get distinct titles including their sub-folder."""
        margo_dir = tmp_path / "margo"
        _write_resource(margo_dir, "resources/screenshots/a.png")
        _write_resource(margo_dir, "resources/other/a.png")

        files, missing = resolve_margo_resource_files({}, margo_dir)

        titles = [f.title for f in files]
        assert titles == ["resources/other/a.png", "resources/screenshots/a.png"]
        assert all(f.media_type == MARGO_RESOURCE_FALLBACK_MEDIA_TYPE for f in files)
        assert missing == []

    def test_referenced_path_escaping_margo_dir_is_missing(self, tmp_path: Path) -> None:
        """A referenced path that resolves outside margo_dir is reported missing and not returned."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        _write_resource(tmp_path, "outside.png", b"\x89PNG")

        files, missing = resolve_margo_resource_files({"icon": "../outside.png"}, margo_dir)

        assert files == []
        assert missing == ["icon"]

    def test_multiple_fields_and_extra_resources(self, tmp_path: Path) -> None:
        """Multiple app.yaml fields plus extra resources should all resolve."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir()

        icon_path = resources_dir / "icon.svg"
        icon_path.write_text("<svg></svg>")
        license_path = resources_dir / "LICENSE"
        license_path.write_text("MIT")
        screenshot_path = resources_dir / "screenshot.png"
        screenshot_path.write_bytes(b"\x89PNG")

        app_yaml = {
            "icon": "resources/icon.svg",
            "licenseFile": "resources/LICENSE",
        }
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 3
        assert missing == []

        # Check that all three files are present with correct media types
        media_types = {f.media_type for f in files}
        assert "application/vnd.margo.app.icon.v1+svg" in media_types
        assert "application/vnd.margo.app.licenseFile.v1+bin" in media_types
        assert MARGO_RESOURCE_FALLBACK_MEDIA_TYPE in media_types

    def test_empty_field_value_ignored(self, tmp_path: Path) -> None:
        """Empty or None field values should be ignored."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()

        app_yaml = {
            "icon": "",
            "licenseFile": None,
        }
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 0
        assert missing == []

    def test_no_resources_dir(self, tmp_path: Path) -> None:
        """If resources/ dir doesn't exist, should just process fields."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        # Don't create resources dir

        app_yaml = {"icon": "resources/icon.svg"}
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 0
        assert missing == ["icon"]

    def test_multiple_missing_fields(self, tmp_path: Path) -> None:
        """Multiple missing referenced files should all be tracked."""
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()

        app_yaml = {
            "icon": "resources/icon.svg",
            "licenseFile": "resources/LICENSE",
            "releaseNotes": "resources/RELEASE.md",
        }
        files, missing = resolve_margo_resource_files(app_yaml, margo_dir)

        assert len(files) == 0
        assert set(missing) == {"icon", "licenseFile", "releaseNotes"}
