"""E2E tests for build command via CLI."""

from pathlib import Path
import re
from typing import Any

from pytest import fixture
from typer.testing import CliRunner

from margot.domain.models import PackageType
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
id: testapp
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
        assert f"Built: {cli_project / '.dist' / '1.0.0' / 'margo'}" in plain.replace("\n", "")

    def test_build_type_compose_only(self, cli_project: Path) -> None:
        """Should build all compose variants and exit 0."""
        result = runner.invoke(app, ["build", "--type", "compose", "--build-dir", str(cli_project / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_count = plain.count("Built")
        assert built_count == 2, f"Expected 2 'Built' lines for compose variants, got {built_count}"
        assert f"Built (default): {cli_project / '.dist' / '1.0.0' / 'testapp-1.0.0.tgz'}" in plain.replace("\n", "")
        assert f"Built (simple): {cli_project / '.dist' / '1.0.0_simple' / 'testapp-1.0.0_simple.tgz'}" in plain.replace("\n", "")

    def test_build_type_quadlet_only(self, cli_project: Path) -> None:
        """Should build all quadlet variants and exit 0."""
        result = runner.invoke(app, ["build", "--type", "quadlet", "--build-dir", str(cli_project / ".dist")])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_count = plain.count("Built")
        assert built_count == 1, f"Expected 1 'Built' line for quadlet variant, got {built_count}"
        assert f"Built (default): {cli_project / '.dist' / '1.0.0' / 'testapp-1.0.0.tgz'}" in plain.replace("\n", "")

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


@fixture
def cli_project_partial(tmp_path: Path, monkeypatch: Any) -> Path:
    """Create a test project with margo.yaml that has margo + quadlet but no compose."""
    (tmp_path / "margo").mkdir()
    (tmp_path / "quadlet" / "default").mkdir(parents=True)

    margo_yaml = tmp_path / "margo.yaml"
    margo_yaml.write_text("""apiVersion: v1
id: testapp
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
quadlet:
  directory: quadlet
  variants:
    - name: default
      version: 1.0.0
""")

    (tmp_path / "margo" / "app.yaml").write_text("name: margo-app\n")
    (tmp_path / "quadlet" / "default" / "app.container").write_text("[Unit]\nDescription=Test\n")

    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestBuildAllSkipsMissingE2E:
    """E2E tests for --type all skipping undefined optional components."""

    def test_build_type_all_skips_missing_compose(self, cli_project_partial: Path) -> None:
        """Should exit 0 and build margo + quadlet even when compose is not defined."""
        result = runner.invoke(
            app,
            ["build", "--type", "all", "--build-dir", str(cli_project_partial / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "Built" in plain

    def test_build_all_reraises_non_skip_value_error(self, cli_project_partial: Path, mocker: Any) -> None:
        """Should exit 1 when --type all triggers a ValueError unrelated to missing component."""

        def _raise_for_compose(package_type: PackageType, **_kwargs: Any) -> list[Any]:
            if package_type.value == "compose":
                raise ValueError("invalid version format")
            return []

        mocker.patch("margot.commands.build.build_service.build", side_effect=_raise_for_compose)

        result = runner.invoke(
            app,
            ["build", "--type", "all", "--build-dir", str(cli_project_partial / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "invalid version format" in plain


class TestBuildMultiType:
    """E2E tests for multiple -t flags."""

    def test_build_multi_type_margo_and_quadlet(self, cli_project: Path) -> None:
        """Should build margo + quadlet when -t margo -t quadlet given; no compose tarballs."""
        result = runner.invoke(
            app,
            ["build", "-t", "margo", "-t", "quadlet", "--build-dir", str(cli_project / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_lines = [line for line in plain.splitlines() if "Built" in line]
        assert len(built_lines) == 2, f"Expected 2 'Built' lines, got {len(built_lines)}: {built_lines}"
        # No compose tarballs should be produced
        dist = cli_project / ".dist"
        tarballs = list(dist.rglob("*.tgz"))
        assert not any("1.0.0_simple" in str(t) for t in tarballs), "No compose-only tarball should exist"

    def test_build_single_type_still_works(self, cli_project: Path) -> None:
        """Should build exactly 1 target with a single -t margo flag."""
        result = runner.invoke(
            app,
            ["build", "-t", "margo", "--build-dir", str(cli_project / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_lines = [line for line in plain.splitlines() if "Built" in line]
        assert len(built_lines) == 1, f"Expected 1 'Built' line, got {len(built_lines)}"

    def test_build_multi_type_with_all_expands(self, cli_project: Path) -> None:
        """Should produce 4 Built lines when -t all is given (same as --type all)."""
        result = runner.invoke(
            app,
            ["build", "-t", "all", "--build-dir", str(cli_project / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_lines = [line for line in plain.splitlines() if "Built" in line]
        assert len(built_lines) == 4, f"Expected 4 'Built' lines, got {len(built_lines)}"

    def test_build_multi_type_deduplicates(self, cli_project: Path) -> None:
        """Should build margo only once even when -t margo -t margo given."""
        result = runner.invoke(
            app,
            ["build", "-t", "margo", "-t", "margo", "--build-dir", str(cli_project / ".dist")],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        built_lines = [line for line in plain.splitlines() if "Built" in line]
        assert len(built_lines) == 1, f"Expected 1 'Built' line after dedup, got {len(built_lines)}"

    def test_build_jinja_descriptor_path(self, cli_project: Path) -> None:
        """The CLI renders app.yaml.jinja into the margo output."""
        (cli_project / "margo" / "app.yaml").unlink()
        (cli_project / "margo" / "app.yaml.jinja").write_text("name: {{ manifest.name }}\n")
        result = runner.invoke(app, ["build", "--type", "margo", "--build-dir", str(cli_project / ".dist")])
        assert result.exit_code == 0
        output = cli_project / ".dist" / "1.0.0" / "margo"
        assert (output / "app.yaml").read_text() == "name: testapp"
        assert not (output / "app.yaml.jinja").exists()

    def test_build_static_descriptor_path(self, cli_project: Path) -> None:
        """The CLI copies a static app.yaml verbatim."""
        (cli_project / "margo" / "app.yaml").write_text("name: unchanged-<app_tag>\n")
        result = runner.invoke(app, ["build", "--type", "margo", "--build-dir", str(cli_project / ".dist")])
        assert result.exit_code == 0
        assert (cli_project / ".dist" / "1.0.0" / "margo" / "app.yaml").read_text() == "name: unchanged-<app_tag>\n"
