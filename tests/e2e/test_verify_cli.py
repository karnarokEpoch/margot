"""E2E tests for verify command via CLI."""

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
  directory: compose
  version: 1.0.0
"""

VALID_APP_YAML = """apiVersion: application.margo.org/v1alpha1
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
          packageLocation: https://example.com/compose.tar.gz
"""

TEMPLATED_APP_YAML = """apiVersion: application.margo.org/v1alpha1
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
          packageLocation: https://example.com/compose.tar.gz
        x-placeholder-extensions:
          vendor-acme:
            ref: {{ manifest.compose.ref }}
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


class TestVerifyHelp:
    """E2E tests for verify command help output."""

    def test_verify_help(self) -> None:
        """Should list the Phase 1 flags."""
        result = runner.invoke(app, ["verify", "--help"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "--project-dir" in plain
        assert "--manifest" in plain
        assert "--schema" in plain

    def test_verify_help_has_no_phase_two_flags(self) -> None:
        """Should not advertise Schema B flags yet."""
        result = runner.invoke(app, ["verify", "--help"])
        plain = _strip_ansi(result.stdout)

        assert "--recommend" not in plain
        assert "--strict" not in plain
        assert "--recommended-schema" not in plain

    def test_verify_is_registered_on_root_help(self) -> None:
        """Should appear in the root command list."""
        result = runner.invoke(app, ["-h"])

        assert result.exit_code == 0
        assert "verify" in _strip_ansi(result.stdout)


class TestVerifyCLI:
    """E2E tests for margot verify."""

    def test_valid_descriptor_exits_0(self, cli_project: Path) -> None:
        """Should pass and print the draft-spec commit line."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "Validated against Margo spec (draft, commit 45f4359)" in plain
        assert "PASS" in plain

    def test_invalid_descriptor_exits_1(self, cli_project: Path) -> None:
        """Should fail with the offending field named in the output."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Validated against Margo spec (draft, commit 45f4359)" in plain
        assert "FAIL" in plain
        assert "'version' is a required property" in plain

    def test_templated_descriptor_exits_0(self, cli_project: Path) -> None:
        """Should render app.yaml.jinja and validate it without a prior build."""
        (cli_project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "PASS" in plain
        assert not (cli_project / "margo" / "app.yaml").exists()

    def test_missing_margo_yaml_exits_1(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Should exit 1 when margo.yaml is absent."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "margo.yaml" in plain

    def test_missing_manifest_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when --manifest points at a missing file."""
        result = runner.invoke(app, ["verify", "--manifest", str(cli_project / "margo" / "absent.yaml")])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Application description not found" in plain

    def test_no_descriptor_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when the margo directory holds no descriptor."""
        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "No app.yaml or app.yaml.jinja found" in plain

    def test_both_descriptor_forms_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when both app.yaml and app.yaml.jinja are present."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")
        (cli_project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Both app.yaml.jinja and app.yaml found" in plain

    def test_unresolved_placeholder_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 with build's unresolved-variable message."""
        (cli_project / "margo" / "app.yaml.jinja").write_text(
            TEMPLATED_APP_YAML.replace("{{ manifest.id }}", "{{ manifest.nope }}"), encoding="utf-8"
        )

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Unresolved Jinja2 variable in app.yaml.jinja" in plain

    def test_malformed_descriptor_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 and report the YAML parse failure as a Schema A error."""
        (cli_project / "margo" / "app.yaml").write_text("kind: [unclosed\n", encoding="utf-8")

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "is not valid YAML" in plain

    def test_explicit_manifest_and_project_dir(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Should verify a descriptor outside the current directory."""
        monkeypatch.chdir(tmp_path)
        descriptor = tmp_path / "elsewhere" / "app.yaml"
        descriptor.parent.mkdir()
        descriptor.write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--project-dir", str(tmp_path), "--manifest", str(descriptor)])
        plain = _output(result)

        assert result.exit_code == 0
        assert "PASS" in plain

    def test_recommend_flag_is_rejected(self, cli_project: Path) -> None:
        """Should reject --recommend: Schema B is not wired in this phase."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])

        assert result.exit_code != 0
        assert "PASS" not in _output(result)

    def test_error_message_regex_is_not_swallowed(self, cli_project: Path) -> None:
        """Should print bracketed regex patterns verbatim (rich markup escaped)."""
        (cli_project / "margo" / "app.yaml").write_text(
            VALID_APP_YAML.replace("id: hello-world", "id: Hello_World"), encoding="utf-8"
        )

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "[a-z0-9-]" in plain


class TestVerifyOutputPaths:
    """E2E tests for the non-error output paths."""

    def test_warning_only_findings_exit_0(self, cli_project: Path) -> None:
        """Should print WARNING lines and still exit 0 when no ERROR is found."""
        (cli_project / "margo" / "app.yaml").write_text("apiVersion: v1\n", encoding="utf-8")
        schema = cli_project / "recommending.linkml.yaml"
        schema.write_text(
            """
id: https://example.org/recommending
name: recommending
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/recommending/
default_prefix: ex
imports:
  - linkml:types
classes:
  ApplicationDescription:
    attributes:
      apiVersion:
        range: string
        required: true
      metadata:
        range: string
        recommended: true
""",
            encoding="utf-8",
        )

        result = runner.invoke(app, ["verify", "--schema", str(schema)])
        plain = _output(result)

        assert result.exit_code == 0
        assert "WARNING" in plain
        assert "is recommended" in plain
        assert "PASS — 1 warning" in plain

    def test_unexpected_failure_exits_1(self, cli_project: Path, mocker: Any) -> None:
        """Should report an unexpected service failure and exit 1."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")
        mocker.patch("margot.commands.verify.verify_service.verify", side_effect=RuntimeError("boom"))

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Verify failed: boom" in plain
