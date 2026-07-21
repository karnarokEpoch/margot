"""E2E tests for build command via CLI."""

from pathlib import Path
import re
from typing import Any

from pytest import fixture
from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


@fixture
def cli_project(tmp_path: Path, monkeypatch: Any) -> Path:
    """Create a test project with margo.yaml and component directories."""
    # Create directory structure
    (tmp_path / "margo").mkdir()
    (tmp_path / "compose" / "default").mkdir(parents=True)
    (tmp_path / "compose" / "simple").mkdir(parents=True)
    (tmp_path / "quadlet" / "default").mkdir(parents=True)

    # Create margo.yaml
    margo_yaml = tmp_path / "margo.yaml"
    margo_yaml.write_text("""apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
compose:
  directory: compose
  variants:
    - name: default
      version: 1.0.0
    - name: simple
      version: 1.0.0_simple
quadlet:
  directory: quadlet
  variants:
    - name: default
      version: 1.0.0
""")

    # Create placeholder files
    (tmp_path / "margo" / "app.yaml").write_text("name: margo-app\n")
    (tmp_path / "compose" / "default" / "compose.yaml").write_text("version: '3'\n")
    (tmp_path / "compose" / "simple" / "compose.yaml").write_text("version: '3'\n")
    (tmp_path / "quadlet" / "default" / "app.container").write_text("[Unit]\nDescription=Test\n")

    # Change to project directory for the test
    monkeypatch.chdir(tmp_path)

    return tmp_path


class TestRootHelp:
    """E2E tests for root-level -h flag."""

    def test_root_help_short_flag(self) -> None:
        """Should display root help with -h and contain 'margot'."""
        result = runner.invoke(app, ["-h"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "margot" in plain


class TestBuildCLI:
    """E2E tests for margot build command."""

    def test_build_help(self) -> None:
        """Should display build command help with expected text."""
        result = runner.invoke(app, ["build", "--help"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "Build Margo" in plain
        assert "--type" in plain
        assert "--version" in plain

    def test_build_help_short_flag(self) -> None:
        """Should display build help with -h shortcut."""
        result = runner.invoke(app, ["build", "-h"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "Build Margo" in plain

    def test_build_type_all_exit_0(self, cli_project: Path) -> None:
        """Should build all components and exit 0."""
        result = runner.invoke(app, ["build", "--type", "all", "--build-dir", str(cli_project / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "Built" in plain
        # Should have 4 builds: 1 margo + 2 compose variants + 1 quadlet variant
        built_count = plain.count("Built")
        assert built_count == 4, f"Expected 4 'Built' lines, got {built_count}"

    def test_build_type_margo_only(self, cli_project: Path) -> None:
        """Should build only margo component and exit 0."""
        result = runner.invoke(app, ["build", "--type", "margo", "--build-dir", str(cli_project / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_count = plain.count("Built")
        assert built_count == 1, f"Expected 1 'Built' line, got {built_count}"
        assert "margo" not in plain.lower() or "Built:" in plain

    def test_build_type_compose_only(self, cli_project: Path) -> None:
        """Should build all compose variants and exit 0."""
        result = runner.invoke(app, ["build", "--type", "compose", "--build-dir", str(cli_project / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_count = plain.count("Built")
        assert built_count == 2, f"Expected 2 'Built' lines for compose variants, got {built_count}"

    def test_build_type_quadlet_only(self, cli_project: Path) -> None:
        """Should build all quadlet variants and exit 0."""
        result = runner.invoke(app, ["build", "--type", "quadlet", "--build-dir", str(cli_project / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_count = plain.count("Built")
        assert built_count == 1, f"Expected 1 'Built' line for quadlet variant, got {built_count}"

    def test_build_variant_simple(self, cli_project: Path) -> None:
        """Should build only the specified compose variant."""
        result = runner.invoke(
            app,
            ["build", "--type", "compose", "--variant", "simple", "--build-dir", str(cli_project / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "[simple]" in plain or "simple" in plain
        built_count = plain.count("Built")
        assert built_count == 1, f"Expected 1 'Built' line for simple variant, got {built_count}"

    def test_build_invalid_type_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 with error message for invalid --type."""
        result = runner.invoke(app, ["build", "--type", "invalid"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "invalid --type" in plain

    def test_build_no_margo_yaml_exits_1(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Should exit 1 when margo.yaml is not found."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["build", "--build-dir", str(tmp_path / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "margo.yaml" in plain.lower()

    def test_build_invalid_semver_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when version is not valid SemVer."""
        result = runner.invoke(
            app,
            ["build", "--type", "margo", "--version", "not-semver", "--build-dir", str(cli_project / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        # Should contain a semver validation error
        assert "semver" in plain.lower() or "version" in plain.lower()

    def test_build_version_override(self, cli_project: Path) -> None:
        """Should accept a valid SemVer version override."""
        result = runner.invoke(
            app,
            ["build", "--type", "margo", "--version", "2.5.3", "--build-dir", str(cli_project / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "Built" in plain
        # The output dir should contain the overridden version
        assert "2.5.3" in plain

    def test_build_variant_not_found_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when requesting a variant that doesn't exist."""
        result = runner.invoke(
            app,
            ["build", "--type", "compose", "--variant", "nonexistent", "--build-dir", str(cli_project / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "nonexistent" in plain or "variant" in plain.lower()

    def test_build_default_build_dir(self, cli_project: Path) -> None:
        """Should use .dist as default build_dir when not specified."""
        result = runner.invoke(app, ["build", "--type", "margo"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "Built" in plain
        # Output should contain .dist directory
        assert ".dist" in plain

    def test_build_short_flags(self, cli_project: Path) -> None:
        """Should accept short flags -t and -v."""
        result = runner.invoke(app, ["build", "-t", "margo", "-v", "1.5.0", "--build-dir", str(cli_project / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "Built" in plain
        assert "1.5.0" in plain

    def test_build_multiple_targets_variant_names(self, cli_project: Path) -> None:
        """Should show variant names in output for compose/quadlet builds."""
        result = runner.invoke(app, ["build", "--type", "compose", "--build-dir", str(cli_project / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        # Should show 2 built lines for the 2 compose variants
        built_count = plain.count("Built")
        assert built_count == 2, f"Expected 2 'Built' lines, got {built_count}"
        # Both variant names should appear in the output
        assert "default" in plain
        assert "simple" in plain
