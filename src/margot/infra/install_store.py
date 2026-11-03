"""Filesystem I/O for `margot install`: the Quadlet root, the ownership marker and file placement.

Domain rules (marker shape, unit names) live in ``margot.domain.install``. This module only
reads and writes files, and it never touches anything outside the application directory it is
given.
"""

from collections.abc import Mapping
import json
import os
from pathlib import Path
import shutil

from margot import console
from margot.domain.install import MARKER_FILENAME, InstallRecord, record_from_dict

_PLACED_MODE_MASK = 0o755  # owner rwx; group and others keep read only, never write


def quadlet_root(environ: Mapping[str, str] | None = None) -> Path:
    """Return the rootless Quadlet directory: ``$XDG_CONFIG_HOME/containers/systemd``.

    ``XDG_CONFIG_HOME`` is used only when absolute (XDG rule); the default is
    ``~/.config/containers/systemd``.
    """
    env = os.environ if environ is None else environ
    home = Path(env["HOME"]) if env.get("HOME") else Path.home()
    config_home = env.get("XDG_CONFIG_HOME", "")
    base = Path(config_home) if config_home and Path(config_home).is_absolute() else home / ".config"
    return base / "containers" / "systemd"


def read_marker(app_dir: Path) -> InstallRecord | None:
    """Read the ownership marker of an application directory; None when there is none.

    Raises:
        ValueError: If the marker exists but is not a readable schema-1 record.
    """
    path = app_dir / MARKER_FILENAME
    if not path.is_file():
        return None
    console.debug(f"Read marker: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{path} is not a readable margot marker ({error}).") from error
    try:
        return record_from_dict(data)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{path}: {error}") from error


def write_marker(app_dir: Path, record: InstallRecord) -> None:
    """Write the marker atomically: a temporary file in the same directory, then ``replace``."""
    app_dir.mkdir(parents=True, exist_ok=True)
    target = app_dir / MARKER_FILENAME
    temporary = app_dir / f".{MARKER_FILENAME}.tmp"
    temporary.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    console.debug(f"Wrote marker: {target}")


def place_file(app_dir: Path, relpath: str, source: Path) -> None:
    """Copy a staged file to ``app_dir/relpath``, keeping sub-directories and the executable bit.

    The mode is at most ``0755``: group and world write bits are never set. The copy goes
    through a temporary sibling file and ``replace``, so a reader never sees a partial file.
    """
    target = app_dir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.margot-tmp")
    shutil.copyfile(source, temporary)
    temporary.chmod((source.stat().st_mode & _PLACED_MODE_MASK) | 0o600)
    temporary.replace(target)
    console.debug(f"Placed {target}")


def remove_file(app_dir: Path, relpath: str) -> None:
    """Delete a file the previous marker listed and the new payload no longer ships."""
    target = app_dir / relpath
    target.unlink(missing_ok=True)
    console.debug(f"Removed stale file {target}")


def prune_empty_dirs(app_dir: Path) -> None:
    """Remove empty sub-directories below the application directory, deepest first."""
    for directory in sorted(app_dir.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            console.debug(f"Removed empty directory {directory}")
