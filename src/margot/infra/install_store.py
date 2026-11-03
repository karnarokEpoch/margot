"""Filesystem I/O for `margot install`: the Quadlet root, the ownership marker and file placement.

Domain rules (marker shape, unit names) live in ``margot.domain.install``. This module only
reads and writes files, and it never touches anything outside the application directory it is
given.
"""

from collections.abc import Iterable, Mapping
import json
import os
from pathlib import Path
import shutil

from margot import console
from margot.domain.install import MARKER_FILENAME, InstallRecord, record_from_dict
from margot.domain.install import search_path_roots as candidate_search_roots

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


def search_path_roots(environ: Mapping[str, str] | None = None, uid: int | None = None) -> tuple[Path, ...]:
    """Return the Quadlet roots of the user manager that exist, in Quadlet's order (sprint-13 §2).

    The runtime root comes from XDG_RUNTIME_DIR, the config root from XDG_CONFIG_HOME (HOME default),
    and the four system roots use ``uid`` (the real user id, as Quadlet does; the UID variable is
    not read). Missing roots are skipped, and roots that resolve to the same directory are listed once.
    """
    env = os.environ if environ is None else environ
    candidates = candidate_search_roots(
        env.get("XDG_RUNTIME_DIR") or None,
        str(quadlet_root(env)),
        os.getuid() if uid is None else uid,
    )
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_dir():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(path)
    console.debug(f"Quadlet search path: {', '.join(str(root) for root in roots) or 'no roots found'}")
    return tuple(roots)


def scan_unit_files(roots: Iterable[Path], exclude_dir: Path | None = None) -> list[str]:
    """List every regular file under the roots, as absolute path strings.

    Hidden directories and ``<unit>.d`` drop-in directories are not entered. When ``exclude_dir`` is given
    (compared by resolved path) that directory is skipped. Names are filtered later by the domain.
    """
    excluded = None if exclude_dir is None else exclude_dir.resolve()
    found: list[str] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            dirnames[:] = [
                name
                for name in dirnames
                if not name.startswith(".")
                and not name.endswith(".d")
                and (excluded is None or (current / name).resolve() != excluded)
            ]
            found.extend(str(current / name) for name in filenames if (current / name).is_file())
    console.debug(f"Scanned {len(found)} file(s) in the Quadlet search path")
    return found


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


def write_tree(files: Mapping[str, Path], destination: Path) -> Path:
    """Copy staged files into ``destination`` at their relative paths: the tree the generator validates.

    The copy keeps every relative path, so unit drop-ins sit beside their units exactly as they will be installed.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for relpath, source in files.items():
        target = destination / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    console.debug(f"Wrote {len(files)} staged file(s) for validation in {destination}")
    return destination


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
