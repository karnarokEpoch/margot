"""Unit tests for infra/filesystem.py archive extraction (top-level strip, hostile archives) and sha256."""

from hashlib import sha256
import io
from pathlib import Path
import tarfile

from pytest import mark, raises

from margot.infra.filesystem import extract_tar_archive, sha256_file


def _write_tar(path: Path, members: list[tuple[str, bytes]]) -> Path:
    """Write a gzip tar with regular file members and return its path."""
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


class TestExtractTarArchive:
    """Safe extraction into a fresh directory."""

    def test_single_top_level_directory_is_stripped(self, tmp_path: Path) -> None:
        """Should strip the one top-level directory (margot's build layout)."""
        archive = _write_tar(tmp_path / "a.tgz", [("name-1.0/web.container", b"[Container]\n")])
        dest = tmp_path / "out"
        dest.mkdir()

        extract_tar_archive(archive, dest)

        assert (dest / "web.container").read_bytes() == b"[Container]\n"
        assert not (dest / "name-1.0").exists()

    def test_archive_without_top_level_directory_keeps_paths(self, tmp_path: Path) -> None:
        """Should keep relative paths when the archive has no single top-level directory."""
        archive = _write_tar(
            tmp_path / "b.tgz",
            [("unit.container", b"x"), ("conf/app.conf", b"y")],
        )
        dest = tmp_path / "out"
        dest.mkdir()

        extract_tar_archive(archive, dest)

        assert (dest / "unit.container").read_bytes() == b"x"
        assert (dest / "conf" / "app.conf").read_bytes() == b"y"

    def test_two_top_level_directories_are_not_stripped(self, tmp_path: Path) -> None:
        """Should not strip when the archive has more than one top-level entry."""
        archive = _write_tar(tmp_path / "c.tgz", [("one/a.container", b"a"), ("two/b.container", b"b")])
        dest = tmp_path / "out"
        dest.mkdir()

        extract_tar_archive(archive, dest)

        assert (dest / "one" / "a.container").exists()
        assert (dest / "two" / "b.container").exists()

    def test_destination_must_be_empty(self, tmp_path: Path) -> None:
        """Should refuse to extract into a directory that already has content."""
        archive = _write_tar(tmp_path / "d.tgz", [("x.container", b"x")])
        dest = tmp_path / "out"
        dest.mkdir()
        (dest / "leftover").write_text("x", encoding="utf-8")

        with raises(ValueError, match="not empty"):
            extract_tar_archive(archive, dest)

    def test_not_a_tar_archive_is_refused(self, tmp_path: Path) -> None:
        """Should report a non-tar file as an invalid archive."""
        bogus = tmp_path / "bogus.tgz"
        bogus.write_text("not a tar", encoding="utf-8")
        dest = tmp_path / "out"
        dest.mkdir()

        with raises(ValueError, match="not a readable tar archive"):
            extract_tar_archive(bogus, dest)

    @mark.parametrize("hostile_name", ["/etc/evil.container", "../escape.container", "sub/../../escape.container"])
    def test_absolute_or_parent_paths_are_refused(self, tmp_path: Path, hostile_name: str) -> None:
        """Should refuse absolute paths and paths that climb out of the destination."""
        archive = _write_tar(tmp_path / "h.tgz", [(hostile_name, b"x")])
        dest = tmp_path / "out"
        dest.mkdir()

        with raises(ValueError, match="unsafe"):
            extract_tar_archive(archive, dest)
        assert not (tmp_path / "escape.container").exists()

    def test_symlink_escaping_the_destination_is_refused(self, tmp_path: Path) -> None:
        """Should refuse a symbolic link that points outside the destination."""
        archive = tmp_path / "link.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="evil")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc"
            tar.addfile(info)
        dest = tmp_path / "out"
        dest.mkdir()

        with raises(ValueError, match="unsafe"):
            extract_tar_archive(archive, dest)

    def test_device_member_is_refused(self, tmp_path: Path) -> None:
        """Should refuse a character device member."""
        archive = tmp_path / "dev.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="null")
            info.type = tarfile.CHRTYPE
            tar.addfile(info)
        dest = tmp_path / "out"
        dest.mkdir()

        with raises(ValueError, match="unsafe"):
            extract_tar_archive(archive, dest)


class TestSha256File:
    """Archive checksum recorded in the marker."""

    def test_sha256_matches_hashlib(self, tmp_path: Path) -> None:
        """Should return the hex sha256 digest of the file content."""
        target = tmp_path / "f.bin"
        target.write_bytes(b"margot")

        assert sha256_file(str(target)) == sha256(b"margot").hexdigest()
