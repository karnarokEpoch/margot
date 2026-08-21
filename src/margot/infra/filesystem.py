"""Pure-Python filesystem helpers for build operations."""

from pathlib import Path
import re
from shutil import copytree, ignore_patterns, rmtree
from tarfile import open as tar_open

from margot import console

SUPPORTED_TAG_PLACEHOLDERS = frozenset({"<app_tag>", "<margo_tag>", "<compose_tag>", "<quadlet_tag>", "<helm_chart_tag>"})


def copy_tree(src: str, dst: str, *, ignore_file: str = ".rsyncignore") -> None:
    """Copy directory tree from src to dst using shutil.copytree."""
    src_path = Path(src)
    dst_path = Path(dst)
    console.debug(f"Copy tree: {src} → {dst}")

    exclude_patterns: list[str] = []
    ignore_path = src_path / ignore_file
    if ignore_path.exists():
        for line in ignore_path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                exclude_patterns.append(stripped)
        console.debug(f"Loaded {len(exclude_patterns)} patterns from {ignore_file}")
        exclude_patterns.append(ignore_file)

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    if dst_path.exists():
        rmtree(dst_path)
        console.debug(f"Removed existing output dir: {dst}")
    ignore_func = ignore_patterns(*exclude_patterns) if exclude_patterns else None
    copytree(src_path, dst_path, ignore=ignore_func, dirs_exist_ok=False)


def substitute_placeholders(  # noqa: C901
    directory: str,
    placeholders: dict[str, str],
    image_config: tuple[str, str] | None = None,
) -> None:
    """Replace supported tag tokens and one optional literal image string in text files.

    Supported tag tokens are ``<app_tag>``, ``<margo_tag>``, ``<compose_tag>``,
    ``<quadlet_tag>``, and ``<helm_chart_tag>``. Unknown ``<..._tag>`` tokens
    are retained and reported as warnings.
    """
    dir_path = Path(directory)
    image_found = False
    image_search = ""
    image_replace = ""
    if image_config is not None:
        image_search, image_replace = image_config
        for placeholder, value in placeholders.items():
            image_replace = image_replace.replace(placeholder, value)

    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        modified_content = content
        for placeholder, value in placeholders.items():
            modified_content = modified_content.replace(placeholder, value)
        if image_config is not None and image_search in modified_content:
            image_found = True
            modified_content = modified_content.replace(image_search, image_replace)

        for unresolved in re.findall(r"<[a-zA-Z0-9_]+_tag>", modified_content):
            if unresolved not in placeholders:
                console.warning(f"Unresolved placeholder '{unresolved}' in {file_path}")

        if modified_content != content:
            file_path.write_text(modified_content, encoding="utf-8")
            console.debug(f"Substituted placeholders in {file_path}")

    if image_config is not None and not image_found:
        console.warning(f"Image search string '{image_config[0]}' not found in any source file in {directory}")


def make_tarball(source_dir: str, output_path: str) -> None:
    """Create a gzip-compressed tarball of source_dir contents at output_path."""
    source_path = Path(source_dir)
    output_file = Path(output_path)
    console.debug(f"Make tarball: {source_dir} → {output_path}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tar_open(output_file, "w:gz") as tar:
        for item in source_path.iterdir():
            tar.add(item, arcname=item.name, recursive=True)
