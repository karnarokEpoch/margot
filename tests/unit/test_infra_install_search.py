"""Unit tests for the search-path listing and scan in infra/install_store.py.

Real directories under tmp_path stand in for the Quadlet roots. The /etc and /usr/share roots are
redirected to tmp_path through the domain constant, so the host's own units never influence a test.
"""

from pathlib import Path
from typing import Any

from pytest import fixture

from margot.domain import install as domain
from margot.infra import install_store


@fixture
def system_roots(tmp_path: Path, monkeypatch: Any) -> dict[str, Path]:
    """Redirect the four system roots into tmp_path and return them by short name."""
    etc = tmp_path / "etc" / "users"
    share = tmp_path / "share" / "users"
    templates = (
        f"{etc}/{{uid}}",
        str(etc),
        f"{share}/{{uid}}",
        str(share),
    )
    monkeypatch.setattr(domain, "SYSTEM_QUADLET_ROOTS", templates)
    return {"etc": etc, "share": share}


class TestSearchPathRoots:
    """Roots come from the environment values; missing roots are skipped and identical roots are kept once."""

    def test_xdg_values_select_runtime_and_config_roots(self, tmp_path: Path, system_roots: dict[str, Path]) -> None:
        """Should use XDG_RUNTIME_DIR and XDG_CONFIG_HOME when both are set and exist."""
        runtime = tmp_path / "run"
        config = tmp_path / "cfg"
        (runtime / "containers" / "systemd").mkdir(parents=True)
        (config / "containers" / "systemd").mkdir(parents=True)

        roots = install_store.search_path_roots(
            {"XDG_RUNTIME_DIR": str(runtime), "XDG_CONFIG_HOME": str(config)}, uid=1000
        )

        assert roots == (runtime / "containers" / "systemd", config / "containers" / "systemd")

    def test_unset_xdg_config_home_falls_back_to_home(self, tmp_path: Path, system_roots: dict[str, Path]) -> None:
        """Should use ~/.config/containers/systemd when XDG_CONFIG_HOME is unset."""
        home = tmp_path / "home"
        (home / ".config" / "containers" / "systemd").mkdir(parents=True)

        roots = install_store.search_path_roots({"HOME": str(home)}, uid=1000)

        assert roots == (home / ".config" / "containers" / "systemd",)

    def test_relative_xdg_config_home_is_ignored(self, tmp_path: Path, system_roots: dict[str, Path]) -> None:
        """Should fall back to HOME when XDG_CONFIG_HOME is relative."""
        home = tmp_path / "home"
        (home / ".config" / "containers" / "systemd").mkdir(parents=True)

        roots = install_store.search_path_roots({"HOME": str(home), "XDG_CONFIG_HOME": "relative/dir"}, uid=1000)

        assert roots == (home / ".config" / "containers" / "systemd",)

    def test_unset_xdg_runtime_dir_drops_the_runtime_root(self, tmp_path: Path, system_roots: dict[str, Path]) -> None:
        """Should list no runtime root when XDG_RUNTIME_DIR is unset."""
        config = tmp_path / "cfg" / "containers" / "systemd"
        config.mkdir(parents=True)

        roots = install_store.search_path_roots({"XDG_CONFIG_HOME": str(tmp_path / "cfg")}, uid=1000)

        assert roots == (config,)

    def test_system_roots_use_the_given_uid(self, tmp_path: Path, system_roots: dict[str, Path]) -> None:
        """Should look under the per-user directory for the uid passed in."""
        per_user = system_roots["etc"] / "4242"
        per_user.mkdir(parents=True)

        roots = install_store.search_path_roots({"XDG_CONFIG_HOME": str(tmp_path / "none")}, uid=4242)

        assert per_user in roots

    def test_identical_roots_are_listed_once(self, tmp_path: Path, system_roots: dict[str, Path]) -> None:
        """Should dedupe roots by resolved path: a runtime dir symlinked to the config dir is one root."""
        real = tmp_path / "real"
        (real / "containers" / "systemd").mkdir(parents=True)
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)

        roots = install_store.search_path_roots(
            {"XDG_RUNTIME_DIR": str(link), "XDG_CONFIG_HOME": str(real)}, uid=1000
        )

        assert len(roots) == 1

    def test_missing_roots_are_skipped(self, tmp_path: Path, system_roots: dict[str, Path]) -> None:
        """Should skip every root that does not exist, without error."""
        assert install_store.search_path_roots({"XDG_CONFIG_HOME": str(tmp_path / "absent")}, uid=1000) == ()


class TestScanUnitFiles:
    """The scan lists files under the roots, pruning hidden directories, drop-in directories and the own directory."""

    def test_scan_lists_units_in_subdirectories_recursively(self, tmp_path: Path) -> None:
        """Should find a unit in a sub-directory of a root."""
        root = tmp_path / "root"
        (root / "sub" / "deep").mkdir(parents=True)
        (root / "sub" / "deep" / "x.container").write_text("", encoding="utf-8")

        found = install_store.scan_unit_files((root,), exclude_dir=tmp_path / "own")

        assert found == [str(root / "sub" / "deep" / "x.container")]

    def test_scan_prunes_hidden_and_drop_in_directories(self, tmp_path: Path) -> None:
        """Should not descend into hidden directories or <unit>.d drop-in directories."""
        root = tmp_path / "root"
        (root / ".hidden").mkdir(parents=True)
        (root / ".hidden" / "a.container").write_text("", encoding="utf-8")
        (root / "web.container.d").mkdir()
        (root / "web.container.d" / "b.container").write_text("", encoding="utf-8")
        (root / "web.container").write_text("", encoding="utf-8")

        found = install_store.scan_unit_files((root,), exclude_dir=tmp_path / "own")

        assert found == [str(root / "web.container")]

    def test_scan_skips_the_own_application_directory(self, tmp_path: Path) -> None:
        """Should not list anything inside the application's own directory, even when it is a root's child."""
        root = tmp_path / "root"
        own = root / "com-own"
        own.mkdir(parents=True)
        (own / "web.container").write_text("", encoding="utf-8")
        (root / "other.container").write_text("", encoding="utf-8")

        found = install_store.scan_unit_files((root,), exclude_dir=own)

        assert found == [str(root / "other.container")]

    def test_scan_returns_hidden_files_for_the_domain_to_ignore(self, tmp_path: Path) -> None:
        """Should return hidden files (the marker) too: the scan prunes hidden directories only, the domain filters names."""
        root = tmp_path / "root"
        sibling = root / "com-other"
        sibling.mkdir(parents=True)
        (sibling / ".margot-install.json").write_text("{}", encoding="utf-8")
        (sibling / "web.container").write_text("", encoding="utf-8")

        found = install_store.scan_unit_files((root,), exclude_dir=tmp_path / "own")

        assert sorted(found) == sorted([str(sibling / ".margot-install.json"), str(sibling / "web.container")])

    def test_scan_of_no_roots_is_empty(self, tmp_path: Path) -> None:
        """Should return an empty list when there are no roots."""
        assert install_store.scan_unit_files((), exclude_dir=tmp_path) == []
