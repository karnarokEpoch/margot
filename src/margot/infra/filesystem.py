"""Pure-Python filesystem helpers for build operations."""

from pathlib import Path
import shutil
import tarfile

from margot import console


def copy_tree(src: str, dst: str, *, ignore_file: str = ".rsyncignore") -> None:
    """Copy directory tree from src to dst using shutil.copytree.

    If dst already exists it is removed first, so the operation is idempotent.

    Args:
        src: Source directory path.
        dst: Destination directory path. Removed and recreated if it already exists.
        ignore_file: Name of ignore file in src (e.g. ".rsyncignore").
                     If it exists, patterns are read and exclusions applied.
    """
    src_path = Path(src)
    dst_path = Path(dst)

    console.debug(f"Copy tree: {src} → {dst}")

    # Read ignore patterns if ignore file exists
    ignore_patterns = []
    ignore_path = src_path / ignore_file
    if ignore_path.exists():
        text = ignore_path.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            # Skip blank lines and comments
            if stripped and not stripped.startswith("#"):
                ignore_patterns.append(stripped)
        console.debug(f"Loaded {len(ignore_patterns)} patterns from {ignore_file}")
        # Always exclude the ignore file itself
        ignore_patterns.append(ignore_file)

    # Create parent directories of dst if needed
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing destination if it already exists (idempotent rebuild)
    if dst_path.exists():
        shutil.rmtree(dst_path)
        console.debug(f"Removed existing output dir: {dst}")

    # Prepare ignore callable
    ignore_func = shutil.ignore_patterns(*ignore_patterns) if ignore_patterns else None

    # Copy tree (dst must not exist)
    shutil.copytree(src_path, dst_path, ignore=ignore_func, dirs_exist_ok=False)


def substitute_placeholders(directory: str, placeholders: dict[str, str]) -> None:
    """Recursively walk all text files in directory and replace placeholders.

    Args:
        directory: Root directory to walk.
        placeholders: Dict of {placeholder_str: replacement_value}.

    Skips:
        - Directories and symlinks to directories.
        - Binary files (UnicodeDecodeError on read).
        - Files with no changes after substitution.
    """
    dir_path = Path(directory)

    for file_path in dir_path.rglob("*"):
        # Skip non-files
        if not file_path.is_file():
            continue

        # Try to read as UTF-8 text
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary file, skip
            continue

        # Apply all placeholders
        modified_content = content
        for placeholder, value in placeholders.items():
            modified_content = modified_content.replace(placeholder, value)

        # Write back only if changed
        if modified_content != content:
            file_path.write_text(modified_content, encoding="utf-8")
            console.debug(f"Substituted placeholders in {file_path}")


def make_tarball(source_dir: str, output_path: str) -> None:
    """Create a gzip-compressed tarball of source_dir contents at output_path.

    The tarball contains the flat contents of source_dir (not the directory itself as root).
    For example: files at source_dir/compose.yaml appear as compose.yaml in the tarball.

    Args:
        source_dir: Source directory to tar.
        output_path: Output tarball path (e.g. /path/to/build-1.0.0.tgz).
    """
    source_path = Path(source_dir)
    output_file = Path(output_path)

    console.debug(f"Make tarball: {source_dir} → {output_path}")

    # Create parent directories of output if needed
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Create tarball with flat contents (arcname="." flattens the directory)
    with tarfile.open(output_file, "w:gz") as tar:
        # Add all contents of source_dir directly (no parent wrapping)
        for item in source_path.iterdir():
            tar.add(
                item,
                arcname=item.name,
                recursive=True,
            )
