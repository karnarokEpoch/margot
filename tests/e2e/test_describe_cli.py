"""E2E tests for describe command via CLI."""

from pathlib import Path
import re
from typing import Any

from pytest import fixture
from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

MARGO_YAML = """apiVersion: v1
id: hello-world
name: Hello World
description: A sample application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo
compose:
  directory: margo
  version: 1.0.0
"""

VALID_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: ApplicationDescription
id: hello-world
metadata:
  name: Hello World
  description: A test application
  version: 1.0.0
  catalog:
    application:
      tagline: Simple test application
    organization:
      - name: Test Org
deploymentProfiles:
  - type: compose
    id: default
    description: Default compose setup
    components:
      - name: hello-compose
        properties:
          repository: oci://example.com/hello
configuration:
  sections:
    - name: Settings
      settings:
        - parameter: testParam
          name: Test Parameter
          description: A test parameter
          immutable: false
          schema: testSchema
  schema:
    - name: testSchema
      dataType: string
      minLength: 1
      maxLength: 100
parameters:
  testParam:
    value: "default-value"
    targets:
      - pointer: settings.test
        components:
          - hello-compose
"""

TEMPLATED_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: {{ manifest.name }}
  version: {{ manifest.version }}
deploymentProfiles:
  - type: compose
    id: default
    components:
      - name: hello-compose
configuration:
  sections: []
  schema: []
parameters: {}
"""

WRONG_KIND_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: SomethingElse
id: hello-world
metadata:
  name: Hello World
  version: 1.0.0
"""


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


def _output(result: Any) -> str:
    """Combine stdout and stderr into plain, ANSI-free text."""
    return _strip_ansi(result.stdout + (result.stderr or ""))


@fixture
def cli_project(tmp_path: Path, monkeypatch: Any) -> Path:
    """Create a project with margo.yaml and an empty margo source directory."""
    (tmp_path / "margo.yaml").write_text(MARGO_YAML, encoding="utf-8")
    (tmp_path / "margo").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestDescribeHelp:
    """E2E tests for describe command help output."""

    def test_describe_help(self) -> None:
        """Should list every flag the command accepts."""
        result = runner.invoke(app, ["describe", "--help"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "--project-dir" in plain
        assert "--manifest" in plain
        assert "--section" in plain

    def test_describe_is_registered_on_root_help(self) -> None:
        """Should appear in the root command list."""
        result = runner.invoke(app, ["-h"])

        assert result.exit_code == 0
        assert "describe" in _strip_ansi(result.stdout)


class TestDescribeCLI:
    """E2E tests for margot describe."""

    def test_describe_valid_descriptor_exits_0(self, cli_project: Path) -> None:
        """Should describe the descriptor and exit 0."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Should show the identity panel with apiVersion as title
        assert "application.margo.org/v1alpha1" in plain or "hello-world" in plain

    def test_describe_missing_margo_yaml_exits_1(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Should exit 1 when margo.yaml is absent."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "margo.yaml" in plain or "Error" in plain

    def test_describe_missing_manifest_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when --manifest points at a missing file."""
        result = runner.invoke(app, ["describe", "--manifest", str(cli_project / "margo" / "absent.yaml")])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Error" in plain or "not found" in plain.lower()

    def test_describe_wrong_kind_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when kind is not ApplicationDescription."""
        (cli_project / "margo" / "app.yaml").write_text(WRONG_KIND_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Error" in plain or "kind" in plain.lower()
        # Should mention running verify
        assert "verify" in plain.lower()

    def test_describe_section_filtering(self, cli_project: Path) -> None:
        """Should render only requested sections."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        # Request only metadata section
        result = runner.invoke(app, ["describe", "--section", "metadata"])
        plain = _output(result)

        assert result.exit_code == 0
        # Should have metadata
        assert "hello-world" in plain or "Hello World" in plain
        # Should not have configuration panel heading
        assert "Configuration" not in plain

    def test_describe_section_order_is_canonical(self, cli_project: Path) -> None:
        """Should always render sections in canonical order regardless of flag order."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        # Request config then metadata
        result1 = runner.invoke(app, ["describe", "--section", "config", "--section", "metadata"])
        # Request metadata then config
        result2 = runner.invoke(app, ["describe", "--section", "metadata", "--section", "config"])
        plain1 = _output(result1)
        plain2 = _output(result2)

        # Both should produce the same output (modulo whitespace)
        assert _strip_ansi(plain1.replace("\n", "")) == _strip_ansi(plain2.replace("\n", ""))

    def test_describe_templated_descriptor_works(self, cli_project: Path) -> None:
        """Should render app.yaml.jinja without requiring a prior build."""
        (cli_project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "hello-world" in plain or "Hello World" in plain
        # Should show path to the template file (not the temp file path)
        assert "app.yaml.jinja" in plain

    def test_describe_with_explicit_manifest_path(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Should describe a descriptor from explicit --manifest path."""
        monkeypatch.chdir(tmp_path)
        descriptor = tmp_path / "elsewhere" / "app.yaml"
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe", "--project-dir", str(tmp_path), "--manifest", str(descriptor)])
        plain = _output(result)

        assert result.exit_code == 0
        assert "hello-world" in plain or "Hello World" in plain

    def test_describe_shows_configuration_settings(self, cli_project: Path) -> None:
        """Should render configuration sections and settings."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Should have configuration section
        assert "Settings" in plain or "Configuration" in plain
        # Should have setting name
        assert "Test Parameter" in plain or "testParam" in plain

    def test_describe_shows_deployment_profiles(self, cli_project: Path) -> None:
        """Should render deployment profiles."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Should show profiles panel with profile type and id
        assert "compose" in plain or "default" in plain
