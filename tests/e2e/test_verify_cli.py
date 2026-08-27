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
        x-placeholder-extensions:
          vendor-acme:
            ref: {{ manifest.compose.ref }}
"""


# Schema A accepts this, Schema B has recommendations about it (no metadata.description,
# no catalog.author, no descriptionFile, no releaseNotes).
SPARSE_APP_YAML = VALID_APP_YAML.replace("  description: A sample application\n", "")

# Satisfies every Schema B recommendation: VALID_APP_YAML leaves out descriptionFile,
# releaseNotes and author, which the spec allows but Schema B recommends.
COMPLIANT_APP_YAML = VALID_APP_YAML.replace(
    "      icon: https://example.com/icon.png\n",
    "      icon: https://example.com/icon.png\n      descriptionFile: README.md\n      releaseNotes: NOTES.md\n",
).replace(
    "    organization:\n",
    "    author:\n      - name: Jane Doe\n        email: jane@example.com\n    organization:\n",
)

SCHEMA_A_SECTION = "── Schema A (Margo spec) ──"
SCHEMA_B_SECTION = "── Schema B (recommended) ──"
DRAFT_SPEC_LINE = "Validated against Margo spec (draft, commit 45f4359)"
ADVISORY_NOTE = "advisory, does not affect the exit code"
STRICT_WITHOUT_SCHEMA_B_WARNING = "--strict has no effect without --recommend or --only-recommend"


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


def _output(result: Any) -> str:
    """Combine stdout and stderr into plain, ANSI-free text."""
    return _strip_ansi(result.stdout + (result.stderr or ""))


def _lines(result: Any) -> list[str]:
    """Return the non-empty output lines, plain and ANSI-free, for exact-output assertions."""
    return [line.rstrip() for line in _output(result).splitlines() if line.strip()]


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
        """Should list every flag the command accepts."""
        result = runner.invoke(app, ["verify", "--help"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "--project-dir" in plain
        assert "--manifest" in plain
        assert "--schema" in plain
        assert "--recommend" in plain
        assert "--recommended-schema" in plain

    def test_verify_help_lists_the_schema_b_gate_flags(self) -> None:
        """Should advertise --strict and --only-recommend: Schema B can gate a run now."""
        result = runner.invoke(app, ["verify", "--help"])
        plain = _strip_ansi(result.stdout)

        assert "--strict" in plain
        assert "--only-recommend" in plain

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

    def test_strict_flag_is_accepted(self, cli_project: Path) -> None:
        """Should accept --strict: with --recommend it turns Schema B into a contract."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend", "--strict"])

        assert result.exit_code == 0
        assert "No such option" not in _output(result)
        assert "PASS" in _output(result)

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


class TestVerifyRecommend:
    """E2E tests for margot verify --recommend."""

    def test_recommend_shows_both_labeled_sections(self, cli_project: Path) -> None:
        """Should label each schema's findings under its own section."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])
        plain = _output(result)

        assert result.exit_code == 0
        assert SCHEMA_A_SECTION in plain
        assert SCHEMA_B_SECTION in plain
        assert plain.index(SCHEMA_A_SECTION) < plain.index(SCHEMA_B_SECTION)

    def test_recommend_reports_schema_b_findings_and_still_exits_0(self, cli_project: Path) -> None:
        """Should print the recommended-slot warnings but keep the run green."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "is recommended" in plain
        assert "advisory, does not affect the exit code" in plain
        assert "verify: PASS" in plain

    def test_schema_b_errors_do_not_change_the_exit_code(self, cli_project: Path) -> None:
        """Should exit 0 on a Schema B ERROR: nothing can fail a run through Schema B yet."""
        descriptor = VALID_APP_YAML[: VALID_APP_YAML.index("    components:")] + "    components: []\n"
        (cli_project / "margo" / "app.yaml").write_text(descriptor, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "verify: PASS" in plain
        assert "should be non-empty" in plain

    def test_clean_descriptor_shows_no_schema_b_section(self, cli_project: Path) -> None:
        """Should suppress the Schema B section when there is nothing at all to report.

        Phase 2 printed an empty section so "ran and clean" differed from "never ran". With
        both schemas clean there is no finding to attribute to either, so the section was pure
        noise: a clean `--recommend` run now reads exactly like a clean default run.
        """
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])

        assert result.exit_code == 0
        assert _lines(result) == [
            DRAFT_SPEC_LINE,
            "Schema A (Margo spec): PASS — no findings",
        ]

    def test_clean_descriptor_prints_no_schema_b_noise(self, cli_project: Path) -> None:
        """Should mention neither Schema B, nor a section separator, nor the advisory note."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "Schema B" not in plain
        assert "──" not in plain
        assert ADVISORY_NOTE not in plain

    def test_clean_descriptor_under_strict_shows_no_schema_b_section(self, cli_project: Path) -> None:
        """Should suppress the section under --strict too: nothing was found, nothing gates."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend", "--strict"])

        assert result.exit_code == 0
        assert _lines(result) == [
            DRAFT_SPEC_LINE,
            "Schema A (Margo spec): PASS — no findings",
        ]

    def test_schema_b_findings_alone_still_show_both_sections(self, cli_project: Path) -> None:
        """Should keep both sections when only Schema B has something to say."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])
        plain = _output(result)

        assert result.exit_code == 0
        assert SCHEMA_A_SECTION in plain
        assert SCHEMA_B_SECTION in plain

    def test_schema_a_findings_alone_still_show_both_sections(self, cli_project: Path) -> None:
        """Should keep both sections when Schema A fails.

        Schema B imports Schema A, so it repeats the same error under its own section — the
        documented consequence of the overlay mechanism, not a second distinct problem.
        """
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])
        plain = _output(result)

        assert result.exit_code == 1
        assert SCHEMA_A_SECTION in plain
        assert SCHEMA_B_SECTION in plain
        assert f"Schema B (recommended): 1 error — {ADVISORY_NOTE}" in plain

    def test_schema_a_failure_still_prints_the_schema_b_section(self, cli_project: Path) -> None:
        """Should print both sections before exiting 1 on a Schema A error."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend"])
        plain = _output(result)

        assert result.exit_code == 1
        assert SCHEMA_A_SECTION in plain
        assert SCHEMA_B_SECTION in plain
        assert "verify: FAIL" in plain

    def test_recommended_schema_override_is_used(self, cli_project: Path) -> None:
        """Should lint against --recommended-schema instead of the bundled Schema B."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")
        schema = cli_project / "custom-recommended.linkml.yaml"
        schema.write_text(
            """
id: https://example.org/custom-recommended
name: custom_recommended
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/custom-recommended/
default_prefix: ex
imports:
  - linkml:types
classes:
  RecommendedApplicationDescription:
    attributes:
      somethingNiceToHave:
        range: string
        recommended: true
""",
            encoding="utf-8",
        )

        result = runner.invoke(app, ["verify", "--recommend", "--recommended-schema", str(schema)])
        plain = _output(result)

        assert result.exit_code == 0
        assert "Slot 'somethingNiceToHave' is recommended" in plain
        assert "verify: PASS" in plain


class TestVerifyStrict:
    """E2E tests for margot verify --strict."""

    def test_strict_without_schema_b_warns_and_keeps_the_exit_code(self, cli_project: Path) -> None:
        """Should warn that --strict has nothing to act on, and behave like a plain run."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--strict"])
        plain = _output(result)

        assert result.exit_code == 0
        assert STRICT_WITHOUT_SCHEMA_B_WARNING in plain
        assert "Schema B" not in plain
        assert "──" not in plain
        assert "Schema A (Margo spec): PASS" in plain

    def test_strict_without_schema_b_still_fails_on_schema_a(self, cli_project: Path) -> None:
        """Should keep exiting 1 on a Schema A error, warning included."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = runner.invoke(app, ["verify", "--strict"])
        plain = _output(result)

        assert result.exit_code == 1
        assert STRICT_WITHOUT_SCHEMA_B_WARNING in plain
        assert "Schema A (Margo spec): FAIL" in plain

    def test_recommend_strict_fails_on_a_schema_b_finding(self, cli_project: Path) -> None:
        """Should exit 1 on a Schema-B-only warning, with Schema A passing."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend", "--strict"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Schema A (Margo spec): PASS" in plain
        assert "is recommended" in plain
        assert "verify: FAIL" in plain

    def test_recommend_strict_drops_the_advisory_note(self, cli_project: Path) -> None:
        """Should not call Schema B advisory: under --strict its findings decide the exit code."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend", "--strict"])
        plain = _output(result)

        assert ADVISORY_NOTE not in plain
        assert "Schema B (recommended): FAIL" in plain

    def test_recommend_strict_fails_on_a_schema_b_error(self, cli_project: Path) -> None:
        """Should exit 1 on a Schema B cardinality error the default run lets through."""
        descriptor = COMPLIANT_APP_YAML[: COMPLIANT_APP_YAML.index("    components:")] + "    components: []\n"
        (cli_project / "margo" / "app.yaml").write_text(descriptor, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend", "--strict"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "should be non-empty" in plain
        assert "verify: FAIL" in plain

    def test_recommend_strict_passes_on_a_compliant_descriptor(self, cli_project: Path) -> None:
        """Should exit 0 when Schema B has nothing to report."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend", "--strict"])

        assert result.exit_code == 0
        assert "FAIL" not in _output(result)


class TestVerifyOnlyRecommend:
    """E2E tests for margot verify --only-recommend."""

    def test_only_recommend_omits_the_schema_a_output(self, cli_project: Path) -> None:
        """Should print no draft-spec line and no Schema A section: Schema A never ran."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--only-recommend"])
        plain = _output(result)

        assert result.exit_code == 0
        assert DRAFT_SPEC_LINE not in plain
        assert "Schema A" not in plain
        assert "──" not in plain

    def test_only_recommend_reports_findings_and_exits_0(self, cli_project: Path) -> None:
        """Should print the recommendations and stay green: Schema B does not gate by default."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--only-recommend"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "is recommended" in plain
        assert ADVISORY_NOTE in plain
        assert "verify: PASS" in plain

    def test_only_recommend_clean_run_prints_two_lines(self, cli_project: Path) -> None:
        """Should print the Schema B summary and the verdict, nothing else."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--only-recommend"])

        assert result.exit_code == 0
        assert _lines(result) == [
            f"Schema B (recommended): no findings — {ADVISORY_NOTE}",
            "verify: PASS",
        ]

    def test_only_recommend_ignores_spec_errors(self, cli_project: Path) -> None:
        """Should exit 0 on a spec-invalid descriptor: nothing gates without --strict."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = runner.invoke(app, ["verify", "--only-recommend"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "'version' is a required property" in plain
        assert "verify: PASS" in plain

    def test_only_recommend_strict_fails_on_a_finding(self, cli_project: Path) -> None:
        """Should exit 1 on any Schema B finding when --strict is set."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--only-recommend", "--strict"])
        plain = _output(result)

        assert result.exit_code == 1
        assert ADVISORY_NOTE not in plain
        assert "Schema B (recommended): FAIL" in plain
        assert "verify: FAIL" in plain

    def test_only_recommend_strict_passes_when_clean(self, cli_project: Path) -> None:
        """Should exit 0 and report the pass verdict when Schema B is clean."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--only-recommend", "--strict"])

        assert result.exit_code == 0
        assert _lines(result) == [
            "Schema B (recommended): PASS — no findings",
            "verify: PASS",
        ]

    def test_only_recommend_verifies_a_templated_descriptor(self, cli_project: Path) -> None:
        """Should render app.yaml.jinja and lint the result, same as every other mode."""
        (cli_project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--only-recommend"])

        assert result.exit_code == 0
        assert "verify: PASS" in _output(result)
        assert not (cli_project / "margo" / "app.yaml").exists()

    def test_only_recommend_with_recommend_is_rejected(self, cli_project: Path) -> None:
        """Should refuse the mutually exclusive pair with a clear error."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--recommend", "--only-recommend"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "--recommend and --only-recommend are mutually exclusive" in plain
        assert "PASS" not in plain

    def test_only_recommend_uses_the_recommended_schema_override(self, cli_project: Path) -> None:
        """Should honour --recommended-schema when Schema B runs alone."""
        (cli_project / "margo" / "app.yaml").write_text(COMPLIANT_APP_YAML, encoding="utf-8")
        schema = cli_project / "custom-recommended.linkml.yaml"
        schema.write_text(
            """
id: https://example.org/custom-recommended
name: custom_recommended
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/custom-recommended/
default_prefix: ex
imports:
  - linkml:types
classes:
  RecommendedApplicationDescription:
    attributes:
      somethingNiceToHave:
        range: string
        recommended: true
""",
            encoding="utf-8",
        )

        result = runner.invoke(app, ["verify", "--only-recommend", "--recommended-schema", str(schema)])
        plain = _output(result)

        assert result.exit_code == 0
        assert "Slot 'somethingNiceToHave' is recommended" in plain

    def test_vendor_extensions_do_not_false_fail(self, cli_project: Path) -> None:
        """Should accept x-placeholder-extensions with Schema B running alone under --strict."""
        descriptor = COMPLIANT_APP_YAML.replace(
            "    components:\n",
            "    x-placeholder-extensions:\n      vendor-acme:\n        profileHint: fast\n    components:\n",
        ).replace(
            "          revision: 1.0.0\n",
            "          revision: 1.0.0\n"
            "        x-placeholder-extensions:\n          vendor-acme:\n            componentHint: quick\n",
        )
        (cli_project / "margo" / "app.yaml").write_text(descriptor, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--only-recommend", "--strict"])

        assert result.exit_code == 0
        assert _lines(result) == [
            "Schema B (recommended): PASS — no findings",
            "verify: PASS",
        ]


class TestVerifyDefaultOutputIsUnchanged:
    """The default (no --recommend) output must stay exactly what Phase 1 shipped."""

    def test_clean_run_prints_only_the_phase_one_lines(self, cli_project: Path) -> None:
        """Should print the draft-spec line and the Schema A verdict, nothing else."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 0
        assert _lines(result) == [
            "Validated against Margo spec (draft, commit 45f4359)",
            "Schema A (Margo spec): PASS — no findings",
        ]

    def test_no_schema_b_noise_without_recommend(self, cli_project: Path) -> None:
        """Should mention neither Schema B nor any section separator."""
        (cli_project / "margo" / "app.yaml").write_text(SPARSE_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "Schema B" not in plain
        assert "──" not in plain
        assert "advisory" not in plain
        assert "verify: PASS" not in plain

    def test_failing_run_prints_only_the_phase_one_lines(self, cli_project: Path) -> None:
        """Should keep the unsectioned failure output, with errors under console.fatal."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 1
        assert _lines(result) == [
            "Validated against Margo spec (draft, commit 45f4359)",
            "Error: ERROR /metadata: 'version' is a required property",
            "Schema A (Margo spec): FAIL — 1 error",
        ]
