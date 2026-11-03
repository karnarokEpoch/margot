"""E2E tests for describe and verify without margo.yaml (Sprint 12 fallback search)."""

from pathlib import Path
import re
from typing import Any

from pytest import fixture
from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

NOT_RENDERABLE_MESSAGE = "Jinja2 templates require margo.yaml context"

MARGO_YAML = """apiVersion: v1
id: hello-world
name: Hello World
description: A sample application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo
compose:
  directory: compose
  version: 1.0.0
"""

VALID_APP_YAML = """apiVersion: v1
kind: ApplicationDescription
id: hello-world
metadata:
  name: Hello World
  description: A sample application
  version: 1.0.0
  catalog:
    application:
      icon: https://example.com/icon.png
    organization:
      - name: Example Corp
deploymentProfiles:
  - type: compose
    id: default
    components:
      - name: hello-world-compose
        properties:
          repository: oci://example.com/compose/hello-world
          revision: 1.0.0
"""

TEMPLATED_APP_YAML = """apiVersion: v1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: {{ manifest.name }}
  description: {{ manifest.description }}
  version: {{ manifest.version }}
  catalog:
    application:
      icon: https://example.com/icon.png
    organization:
      - name: Example Corp
deploymentProfiles:
  - type: compose
    id: default
    components:
      - name: {{ manifest.compose.component }}
        properties:
          repository: oci://example.com/compose/hello-world
          revision: 1.0.0
"""


def _named(name: str) -> str:
    """Return the valid descriptor with a different metadata.name, to tell copies apart in output."""
    return VALID_APP_YAML.replace("  name: Hello World\n", f"  name: {name}\n")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


def _output(result: Any) -> str:
    """Combine stdout and stderr into plain, ANSI-free text."""
    return _strip_ansi(result.stdout + (result.stderr or ""))


@fixture
def bare_cwd(tmp_path: Path, monkeypatch: Any) -> Path:
    """Run from an empty directory with no margo.yaml; the project is the cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@fixture
def elsewhere(tmp_path: Path, monkeypatch: Any) -> Path:
    """Run from an unrelated directory so --project-dir is the only way to reach the project."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return tmp_path / "project"


class TestRootAppYamlWithoutMargoYaml:
    """A bare app.yaml at the project root resolves with no margo.yaml."""

    def test_verify_exits_0_from_the_project_directory(self, bare_cwd: Path) -> None:
        """Should pass verify when run from a directory holding only app.yaml."""
        (bare_cwd / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 0
        assert "PASS" in _output(result)

    def test_describe_exits_0_from_the_project_directory(self, bare_cwd: Path) -> None:
        """Should describe the application when run from a directory holding only app.yaml."""
        (bare_cwd / "app.yaml").write_text(_named("Root App"), encoding="utf-8")

        result = runner.invoke(app, ["describe"])

        assert result.exit_code == 0
        assert "Root App" in _output(result)

    def test_verify_exits_0_with_project_dir(self, elsewhere: Path) -> None:
        """Should pass verify when --project-dir points at a directory holding only app.yaml."""
        elsewhere.mkdir()
        (elsewhere / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--project-dir", str(elsewhere)])

        assert result.exit_code == 0
        assert "PASS" in _output(result)

    def test_describe_exits_0_with_project_dir(self, elsewhere: Path) -> None:
        """Should describe the application when --project-dir points at a directory holding only app.yaml."""
        elsewhere.mkdir()
        (elsewhere / "app.yaml").write_text(_named("Root App"), encoding="utf-8")

        result = runner.invoke(app, ["describe", "--project-dir", str(elsewhere)])

        assert result.exit_code == 0
        assert "Root App" in _output(result)


class TestMargoSubdirAppYamlWithoutMargoYaml:
    """The margo/app.yaml layout resolves with no margo.yaml, and the root copy wins when both exist."""

    def test_verify_exits_0_from_the_project_directory(self, bare_cwd: Path) -> None:
        """Should pass verify on margo/app.yaml when no margo.yaml and no root app.yaml exist."""
        (bare_cwd / "margo").mkdir()
        (bare_cwd / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 0
        assert "PASS" in _output(result)

    def test_describe_exits_0_with_project_dir(self, elsewhere: Path) -> None:
        """Should describe margo/app.yaml when --project-dir points at the project."""
        (elsewhere / "margo").mkdir(parents=True)
        (elsewhere / "margo" / "app.yaml").write_text(_named("Subdir App"), encoding="utf-8")

        result = runner.invoke(app, ["describe", "--project-dir", str(elsewhere)])

        assert result.exit_code == 0
        assert "Subdir App" in _output(result)

    def test_root_app_yaml_wins_over_margo_subdir_for_verify(self, bare_cwd: Path) -> None:
        """Should verify the valid root app.yaml and ignore a broken margo/app.yaml beside it."""
        (bare_cwd / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")
        (bare_cwd / "margo").mkdir()
        (bare_cwd / "margo" / "app.yaml").write_text(VALID_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 0
        assert "PASS" in _output(result)

    def test_root_app_yaml_wins_over_margo_subdir_for_describe(self, bare_cwd: Path) -> None:
        """Should describe the root app.yaml and not the margo/app.yaml copy."""
        (bare_cwd / "app.yaml").write_text(_named("Root App"), encoding="utf-8")
        (bare_cwd / "margo").mkdir()
        (bare_cwd / "margo" / "app.yaml").write_text(_named("Subdir App"), encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "Root App" in plain
        assert "Subdir App" not in plain


class TestJinjaWithoutMargoYamlExits3:
    """A template cannot render without margo.yaml, so the fallback reports an actionable error."""

    def test_verify_jinja_without_margo_yaml_exits_3(self, bare_cwd: Path) -> None:
        """Should exit 3 with the render-context hint when verify finds app.yaml.jinja and no margo.yaml."""
        (bare_cwd / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 3
        assert NOT_RENDERABLE_MESSAGE in _output(result)

    def test_describe_jinja_without_margo_yaml_exits_3(self, bare_cwd: Path) -> None:
        """Should exit 3 with the render-context hint when describe finds app.yaml.jinja and no margo.yaml."""
        (bare_cwd / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])

        assert result.exit_code == 3
        assert NOT_RENDERABLE_MESSAGE in _output(result)

    def test_describe_jinja_in_margo_subdir_without_margo_yaml_exits_3(self, elsewhere: Path) -> None:
        """Should exit 3 when the only template sits in margo/ and --project-dir points at the project."""
        (elsewhere / "margo").mkdir(parents=True)
        (elsewhere / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe", "--project-dir", str(elsewhere)])

        assert result.exit_code == 3
        assert NOT_RENDERABLE_MESSAGE in _output(result)

    def test_describe_without_any_descriptor_exits_3(self, bare_cwd: Path) -> None:
        """Should exit 3 and name both static paths searched when no descriptor exists."""
        result = runner.invoke(app, ["describe"])

        assert result.exit_code == 3
        assert "Searched: app.yaml, margo/app.yaml" in _output(result)
