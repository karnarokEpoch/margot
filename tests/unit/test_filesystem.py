"""Unit tests for infra/filesystem.py filesystem helpers."""

from pathlib import Path
import tarfile
from typing import Any
from unittest.mock import MagicMock

from pytest import fixture

from margot.infra.filesystem import copy_tree, make_tarball, substitute_placeholders


@fixture
def mock_console(mocker: Any) -> MagicMock:
    """Mock console.debug for assertion without capturing output."""
    return mocker.patch("margot.infra.filesystem.console.debug")


class TestCopyTree:
    """Tests for copy_tree function."""

    def test_copy_tree_copies_all_files_when_no_ignore_file(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should copy all files when no ignore file present."""
        # Setup
        src = tmp_path / "src"
        src.mkdir()
        (src / "file1.txt").write_text("content1")
        (src / "file2.py").write_text("content2")
        subdir = src / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("content3")

        dst = tmp_path / "dst"

        # Execute
        copy_tree(str(src), str(dst))

        # Assert
        assert dst.exists()
        assert (dst / "file1.txt").read_text() == "content1"
        assert (dst / "file2.py").read_text() == "content2"
        assert (dst / "subdir" / "file3.txt").read_text() == "content3"

    def test_copy_tree_respects_rsyncignore_patterns(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should respect .rsyncignore patterns to exclude files."""
        # Setup
        src = tmp_path / "src"
        src.mkdir()
        (src / ".rsyncignore").write_text("*.log\n")
        (src / "keep.txt").write_text("keep me")
        (src / "ignore.log").write_text("ignore me")

        dst = tmp_path / "dst"

        # Execute
        copy_tree(str(src), str(dst))

        # Assert
        assert dst.exists()
        assert (dst / "keep.txt").exists()
        assert not (dst / "ignore.log").exists()
        assert not (dst / ".rsyncignore").exists()  # Ignore file itself is excluded

    def test_copy_tree_ignores_blank_lines_and_comments_in_ignore_file(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should ignore blank lines and # comments in .rsyncignore."""
        # Setup
        src = tmp_path / "src"
        src.mkdir()
        (src / ".rsyncignore").write_text("# Comment line\n\n*.log\n# Another comment\n")
        (src / "keep.txt").write_text("keep me")
        (src / "ignore.log").write_text("ignore me")

        dst = tmp_path / "dst"

        # Execute
        copy_tree(str(src), str(dst))

        # Assert
        assert (dst / "keep.txt").exists()
        assert not (dst / "ignore.log").exists()

    def test_copy_tree_raises_file_exists_error_if_dst_exists(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should raise FileExistsError if dst already exists — kept for docs only.

        NOTE: copy_tree now removes an existing dst before copying (idempotent).
        This test verifies the OLD behaviour is gone: no FileExistsError is raised.
        """
        # Setup
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("content")

        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "old_file.txt").write_text("old content")

        # copy_tree should NOT raise — it removes and recreates
        copy_tree(str(src), str(dst))
        assert (dst / "file.txt").read_text() == "content"
        assert not (dst / "old_file.txt").exists()

    def test_copy_tree_overwrites_existing_destination(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should replace dst entirely: new file present, old file absent."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("new content")

        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "old_file.txt").write_text("stale content")

        copy_tree(str(src), str(dst))

        assert (dst / "file.txt").read_text() == "new content"
        assert not (dst / "old_file.txt").exists()

    def test_copy_tree_idempotent_second_run(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Second call to copy_tree should succeed and produce identical output."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("content")

        dst = tmp_path / "dst"

        copy_tree(str(src), str(dst))
        copy_tree(str(src), str(dst))  # Should not raise FileExistsError

        assert (dst / "file.txt").read_text() == "content"

    def test_copy_tree_creates_parent_directories_if_needed(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should create parent directories of dst if they don't exist."""
        # Setup
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("content")

        dst = tmp_path / "a" / "b" / "c" / "dst"

        # Execute
        copy_tree(str(src), str(dst))

        # Assert
        assert dst.exists()
        assert (dst / "file.txt").read_text() == "content"

    def test_copy_tree_emits_debug_messages(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should emit debug messages for src, dst, and patterns."""
        # Setup
        src = tmp_path / "src"
        src.mkdir()
        (src / ".rsyncignore").write_text("*.log\n")
        (src / "file.txt").write_text("content")

        dst = tmp_path / "dst"

        # Execute
        copy_tree(str(src), str(dst))

        # Assert
        calls = [call.args[0] for call in mock_console.call_args_list]
        assert any("Copy tree:" in call for call in calls)
        assert any("Loaded 1 patterns" in call for call in calls)


class TestSubstitutePlaceholders:
    """Tests for substitute_placeholders function."""

    def test_substitute_placeholders_in_text_file(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should substitute a placeholder in a text file."""
        # Setup
        directory = tmp_path / "dir"
        directory.mkdir()
        file_path = directory / "file.txt"
        file_path.write_text("Version: <app_tag>")

        # Execute
        substitute_placeholders(str(directory), {"<app_tag>": "1.0.0"})

        # Assert
        assert file_path.read_text() == "Version: 1.0.0"

    def test_substitute_placeholders_multiple_in_one_pass(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should substitute multiple placeholders in one pass."""
        # Setup
        directory = tmp_path / "dir"
        directory.mkdir()
        file_path = directory / "file.txt"
        file_path.write_text("App: <app_tag>, Compose: <compose_tag>")

        # Execute
        substitute_placeholders(
            str(directory),
            {"<app_tag>": "1.0.0", "<compose_tag>": "2.0.0"},
        )

        # Assert
        assert file_path.read_text() == "App: 1.0.0, Compose: 2.0.0"

    def test_substitute_placeholders_leaves_binary_files_untouched(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should skip binary files (UnicodeDecodeError) with no error."""
        # Setup
        directory = tmp_path / "dir"
        directory.mkdir()
        binary_file = directory / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03")

        # Execute (should not raise)
        substitute_placeholders(str(directory), {"<app_tag>": "1.0.0"})

        # Assert
        assert binary_file.read_bytes() == b"\x00\x01\x02\x03"

    def test_substitute_placeholders_does_not_rewrite_if_no_changes(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should not rewrite files that have no placeholders."""
        # Setup
        directory = tmp_path / "dir"
        directory.mkdir()
        file_path = directory / "file.txt"
        file_path.write_text("No placeholders here")

        # Execute
        substitute_placeholders(str(directory), {"<app_tag>": "1.0.0"})

        # Assert (verify no write happened)
        assert file_path.read_text() == "No placeholders here"
        # Verify debug not called for this file
        calls = [call.args[0] for call in mock_console.call_args_list]
        assert not any("file.txt" in call for call in calls)

    def test_substitute_placeholders_emits_debug_per_modified_file(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should emit debug message per file modified."""
        # Setup
        directory = tmp_path / "dir"
        directory.mkdir()
        (directory / "file1.txt").write_text("Version: <app_tag>")
        (directory / "file2.txt").write_text("Version: <app_tag>")

        # Execute
        substitute_placeholders(str(directory), {"<app_tag>": "1.0.0"})

        # Assert
        calls = [call.args[0] for call in mock_console.call_args_list]
        assert any("file1.txt" in call for call in calls)
        assert any("file2.txt" in call for call in calls)

    def test_substitute_placeholders_in_nested_directories(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should walk nested directories and substitute placeholders."""
        # Setup
        directory = tmp_path / "dir"
        directory.mkdir()
        subdir = directory / "subdir"
        subdir.mkdir()
        (directory / "file1.txt").write_text("App: <app_tag>")
        (subdir / "file2.txt").write_text("App: <app_tag>")

        # Execute
        substitute_placeholders(str(directory), {"<app_tag>": "1.0.0"})

        # Assert
        assert (directory / "file1.txt").read_text() == "App: 1.0.0"
        assert (subdir / "file2.txt").read_text() == "App: 1.0.0"


class TestMakeTarball:
    """Tests for make_tarball function."""

    def test_make_tarball_creates_tgz_file(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should create a .tgz file at the given path."""
        # Setup
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "file.txt").write_text("content")

        output_path = tmp_path / "output.tgz"

        # Execute
        make_tarball(str(source_dir), str(output_path))

        # Assert
        assert output_path.exists()
        assert output_path.suffix == ".tgz"

    def test_make_tarball_flat_contents_no_parent_wrapping(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should contain flat contents (no parent dir wrapping)."""
        # Setup
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "compose.yaml").write_text("version: 3")
        (source_dir / "config.json").write_text("{}")

        output_path = tmp_path / "build-1.0.0.tgz"

        # Execute
        make_tarball(str(source_dir), str(output_path))

        # Assert - verify tarball contains files at root, not nested
        with tarfile.open(output_path, "r:gz") as tar:
            names = tar.getnames()
            assert "compose.yaml" in names
            assert "config.json" in names
            assert not any("source/" in name for name in names)

    def test_make_tarball_works_with_nested_subdirectories(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should work with nested subdirectories inside source dir."""
        # Setup
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        subdir = source_dir / "subdir"
        subdir.mkdir()
        (source_dir / "file1.txt").write_text("content1")
        (subdir / "file2.txt").write_text("content2")

        output_path = tmp_path / "archive.tgz"

        # Execute
        make_tarball(str(source_dir), str(output_path))

        # Assert
        with tarfile.open(output_path, "r:gz") as tar:
            names = tar.getnames()
            assert "file1.txt" in names
            assert "subdir/file2.txt" in names

    def test_make_tarball_creates_parent_directories(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should create parent directories of output_path if needed."""
        # Setup
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "file.txt").write_text("content")

        output_path = tmp_path / "a" / "b" / "c" / "archive.tgz"

        # Execute
        make_tarball(str(source_dir), str(output_path))

        # Assert
        assert output_path.exists()
        assert output_path.parent.exists()

    def test_make_tarball_emits_debug_message(
        self, tmp_path: Path, mock_console: MagicMock
    ) -> None:
        """Should emit debug message with source and output path."""
        # Setup
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "file.txt").write_text("content")

        output_path = tmp_path / "archive.tgz"

        # Execute
        make_tarball(str(source_dir), str(output_path))

        # Assert
        calls = [call.args[0] for call in mock_console.call_args_list]
        assert any("Make tarball:" in call for call in calls)
        assert any(str(source_dir) in call for call in calls)
        assert any(str(output_path) in call for call in calls)
