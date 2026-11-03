"""Unit tests for infra/install_store.py: XDG path, ownership marker I/O, file placement and cleanup."""

import json
from pathlib import Path

from pytest import fixture, raises

from margot.domain.install import MARKER_FILENAME, ComponentEntry, InstallRecord, SourceRecord
from margot.infra import install_store


@fixture
def record() -> InstallRecord:
    """An installed record with one component."""
    return InstallRecord(
        state="installed",
        app_id="com-example-app",
        app_name="Example",
        app_version="1.0.0",
        profile_id="quadlet-v1",
        installed_at="2026-11-03T10:00:00Z",
        source=SourceRecord(kind="project", uri=None, path="/work/.dist"),
        components=(
            ComponentEntry(name="web", repository=None, revision="1.0.0", archive_sha256="0" * 64, files=("web.container",)),
        ),
        services=("web.service",),
        parameters=(),
    )


class TestQuadletRoot:
    """XDG-aware rootless Quadlet directory."""

    def test_default_is_home_config_containers_systemd(self, tmp_path: Path) -> None:
        """Should default to ~/.config/containers/systemd when XDG_CONFIG_HOME is unset."""
        assert install_store.quadlet_root({"HOME": str(tmp_path)}) == tmp_path / ".config" / "containers" / "systemd"

    def test_xdg_config_home_is_honoured(self, tmp_path: Path) -> None:
        """Should use XDG_CONFIG_HOME when it is an absolute path."""
        root = install_store.quadlet_root({"XDG_CONFIG_HOME": str(tmp_path / "cfg")})
        assert root == tmp_path / "cfg" / "containers" / "systemd"

    def test_relative_xdg_config_home_is_ignored(self, tmp_path: Path) -> None:
        """Should fall back to the default when XDG_CONFIG_HOME is relative (XDG rule)."""
        root = install_store.quadlet_root({"HOME": str(tmp_path), "XDG_CONFIG_HOME": "rel"})
        assert root == tmp_path / ".config" / "containers" / "systemd"


class TestMarker:
    """Atomic marker read/write."""

    def test_missing_marker_reads_as_none(self, tmp_path: Path) -> None:
        """Should return None when the application directory has no marker."""
        assert install_store.read_marker(tmp_path) is None

    def test_write_then_read_round_trips(self, tmp_path: Path, record: InstallRecord) -> None:
        """Should write the marker file and read back the same record."""
        install_store.write_marker(tmp_path, record)

        assert (tmp_path / MARKER_FILENAME).is_file()
        assert install_store.read_marker(tmp_path) == record

    def test_write_leaves_no_temp_file_behind(self, tmp_path: Path, record: InstallRecord) -> None:
        """Should replace the marker atomically, leaving only the final file."""
        install_store.write_marker(tmp_path, record)

        assert sorted(p.name for p in tmp_path.iterdir()) == [MARKER_FILENAME]

    def test_corrupt_marker_is_a_value_error(self, tmp_path: Path) -> None:
        """Should refuse a marker that is not valid JSON, naming the file."""
        (tmp_path / MARKER_FILENAME).write_text("{not json", encoding="utf-8")

        with raises(ValueError, match=MARKER_FILENAME):
            install_store.read_marker(tmp_path)

    def test_marker_with_wrong_shape_is_a_value_error(self, tmp_path: Path) -> None:
        """Should refuse a marker that is valid JSON but not a margot record."""
        (tmp_path / MARKER_FILENAME).write_text(json.dumps({"schema": 1}), encoding="utf-8")

        with raises(ValueError, match="invalid state"):
            install_store.read_marker(tmp_path)


class TestPlacement:
    """File placement, stale-file removal and empty-directory pruning."""

    def test_place_file_keeps_relative_layout_and_content(self, tmp_path: Path) -> None:
        """Should create sub-directories and copy the content to the relative path."""
        source = tmp_path / "staged.conf"
        source.write_text("x=1\n", encoding="utf-8")
        app = tmp_path / "app"
        app.mkdir()

        install_store.place_file(app, "conf/nginx.conf", source)

        assert (app / "conf" / "nginx.conf").read_text(encoding="utf-8") == "x=1\n"

    def test_group_and_world_write_bits_are_cleared(self, tmp_path: Path) -> None:
        """Should keep the owner-writable mode but never group/world-writable."""
        source = tmp_path / "staged"
        source.write_text("x", encoding="utf-8")
        source.chmod(0o666)
        app = tmp_path / "app"
        app.mkdir()

        install_store.place_file(app, "a.container", source)

        assert (app / "a.container").stat().st_mode & 0o777 == 0o644

    def test_executable_bit_is_preserved(self, tmp_path: Path) -> None:
        """Should keep the executable bit of a payload file."""
        source = tmp_path / "script"
        source.write_text("#!/bin/sh\n", encoding="utf-8")
        source.chmod(0o755)
        app = tmp_path / "app"
        app.mkdir()

        install_store.place_file(app, "bin/script", source)

        assert (app / "bin" / "script").stat().st_mode & 0o777 == 0o755

    def test_placing_again_replaces_content(self, tmp_path: Path) -> None:
        """Should overwrite an existing file on upgrade."""
        app = tmp_path / "app"
        app.mkdir()
        first = tmp_path / "one"
        first.write_text("old", encoding="utf-8")
        second = tmp_path / "two"
        second.write_text("new", encoding="utf-8")
        install_store.place_file(app, "a.container", first)

        install_store.place_file(app, "a.container", second)

        assert (app / "a.container").read_text(encoding="utf-8") == "new"

    def test_remove_file_ignores_missing_file(self, tmp_path: Path) -> None:
        """Should not fail when a stale file is already gone."""
        install_store.remove_file(tmp_path, "gone.container")

    def test_prune_removes_empty_directories_only(self, tmp_path: Path) -> None:
        """Should remove empty sub-directories but keep the application directory and non-empty ones."""
        (tmp_path / "empty" / "deeper").mkdir(parents=True)
        (tmp_path / "kept").mkdir()
        (tmp_path / "kept" / "f.conf").write_text("x", encoding="utf-8")

        install_store.prune_empty_dirs(tmp_path)

        assert not (tmp_path / "empty").exists()
        assert (tmp_path / "kept" / "f.conf").exists()
        assert tmp_path.exists()
