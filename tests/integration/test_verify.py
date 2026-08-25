"""Integration tests for services/verify.py against the real vendored Margo spec schema."""

from pathlib import Path
from typing import Any

from pytest import fixture, raises

from margot.domain.validation import Severity
from margot.schemas import SCHEMA_A_COMMIT
from margot.services import verify as verify_module
from margot.services.verify import resolve_descriptor, verify

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
      descriptionFile: README.md
      releaseNotes: NOTES.md
    author:
      - name: Jane Doe
        email: jane@example.com
    organization:
      - name: Example Corp
        site: https://example.com
deploymentProfiles:
  - type: compose
    id: default
    components:
      - name: hello-world-compose
        properties:
          packageLocation: https://example.com/compose.tar.gz
x-placeholder-extensions:
  vendor-acme:
    topLevel: true
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


@fixture
def project(tmp_path: Path) -> Path:
    """Create a project with margo.yaml and an empty margo source directory."""
    (tmp_path / "margo.yaml").write_text(MARGO_YAML, encoding="utf-8")
    (tmp_path / "margo").mkdir()
    return tmp_path


class TestVerifyStaticDescriptor:
    """Verification of a static app.yaml."""

    def test_good_descriptor_passes(self, project: Path) -> None:
        """Should pass with no findings against the real vendored schema."""
        (project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.schema_a_results == []
        assert result.passed is True

    def test_result_reports_pinned_schema_commit(self, project: Path) -> None:
        """Should report the pinned draft commit and no Schema B findings."""
        (project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.schema_a_version == SCHEMA_A_COMMIT
        assert result.schema_b_results == []

    def test_bad_descriptor_reports_schema_a_error(self, project: Path) -> None:
        """Should fail with an ERROR naming the missing required field."""
        (project / "margo" / "app.yaml").write_text(VALID_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.passed is False
        assert any(
            finding.severity is Severity.ERROR and "'version' is a required property" in finding.message
            for finding in result.schema_a_results
        )

    def test_unexpected_field_is_an_error(self, project: Path) -> None:
        """Should reject fields the spec does not declare."""
        (project / "margo" / "app.yaml").write_text(f"{VALID_APP_YAML}notASpecField: true\n", encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.passed is False
        assert any("Additional properties are not allowed" in finding.message for finding in result.schema_a_results)

    def test_vendor_extensions_do_not_false_fail(self, project: Path) -> None:
        """Should accept x-placeholder-extensions at every level the spec allows them."""
        descriptor = VALID_APP_YAML.replace(
            "    components:\n",
            "    x-placeholder-extensions:\n      vendor-acme:\n        profileHint: fast\n    components:\n",
        ).replace(
            "          packageLocation: https://example.com/compose.tar.gz\n",
            "          packageLocation: https://example.com/compose.tar.gz\n"
            "        x-placeholder-extensions:\n          vendor-acme:\n            componentHint: quick\n",
        )
        (project / "margo" / "app.yaml").write_text(descriptor, encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.schema_a_results == []
        assert result.passed is True

    def test_yaml_parse_failure_is_a_hard_schema_a_failure(self, project: Path) -> None:
        """Should turn an unparseable descriptor into a Schema A ERROR, not an exception."""
        (project / "margo" / "app.yaml").write_text("kind: [unclosed\n", encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.passed is False
        assert [finding.severity for finding in result.schema_a_results] == [Severity.ERROR]
        assert "is not valid YAML" in result.schema_a_results[0].message

    def test_non_mapping_descriptor_is_a_hard_failure(self, project: Path) -> None:
        """Should reject a descriptor whose root is not a mapping."""
        (project / "margo" / "app.yaml").write_text("- one\n- two\n", encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.passed is False
        assert "Expected a YAML mapping at the document root." in result.schema_a_results[0].message


class TestVerifyTemplatedDescriptor:
    """Verification of an app.yaml.jinja template, without a prior build."""

    def test_templated_descriptor_verifies_without_build(self, project: Path) -> None:
        """Should render the template in place and validate the result."""
        (project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.schema_a_results == []
        assert result.passed is True
        assert not (project / "margo" / "app.yaml").exists()
        assert not (project / ".dist").exists()

    def test_templated_descriptor_errors_are_reported(self, project: Path) -> None:
        """Should report Schema A errors produced by the rendered output."""
        broken = TEMPLATED_APP_YAML.replace("  version: {{ manifest.version }}", "  nope: {{ manifest.version }}")
        (project / "margo" / "app.yaml.jinja").write_text(broken, encoding="utf-8")

        result = verify(project_dir=str(project))

        assert result.passed is False
        assert any("'version' is a required property" in finding.message for finding in result.schema_a_results)

    def test_unresolved_placeholder_fails_like_build(self, project: Path) -> None:
        """Should raise the same message shape build raises for an undefined variable."""
        (project / "margo" / "app.yaml.jinja").write_text(
            TEMPLATED_APP_YAML.replace("{{ manifest.id }}", "{{ manifest.unknown_field }}"), encoding="utf-8"
        )

        with raises(ValueError, match=r"Unresolved Jinja2 variable in app.yaml.jinja:"):
            verify(project_dir=str(project))

    def test_temp_file_is_deleted(self, project: Path, mocker: Any) -> None:
        """Should delete the rendered temporary file once validation is done."""
        (project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")
        spy = mocker.spy(verify_module, "write_temp_text")

        verify(project_dir=str(project))

        assert spy.call_count == 1
        assert not Path(spy.spy_return).exists()


class TestDescriptorResolution:
    """Tests for the standalone resolve_descriptor function."""

    def test_static_descriptor_is_returned_as_is(self, project: Path) -> None:
        """Should return the on-disk path and no temp file for a static app.yaml."""
        descriptor_path = project / "margo" / "app.yaml"
        descriptor_path.write_text(VALID_APP_YAML, encoding="utf-8")

        resolved = resolve_descriptor(str(project))

        assert resolved.path == str(descriptor_path)
        assert resolved.source_path == str(descriptor_path)
        assert resolved.rendered is False
        assert resolved.meta is not None
        assert resolved.meta.id == "hello-world"

    def test_template_is_rendered_to_a_temp_file(self, project: Path) -> None:
        """Should render to a temp file the caller must delete."""
        template_path = project / "margo" / "app.yaml.jinja"
        template_path.write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        resolved = resolve_descriptor(str(project))
        try:
            assert resolved.rendered is True
            assert resolved.path != str(template_path)
            assert resolved.source_path == str(template_path)
            assert "hello-world-compose" in Path(resolved.path).read_text(encoding="utf-8")
        finally:
            Path(resolved.path).unlink()

    def test_explicit_manifest_overrides_margo_yaml(self, tmp_path: Path) -> None:
        """Should use --manifest as-is, with no margo.yaml required."""
        descriptor_path = tmp_path / "elsewhere" / "app.yaml"
        descriptor_path.parent.mkdir()
        descriptor_path.write_text(VALID_APP_YAML, encoding="utf-8")

        resolved = resolve_descriptor(str(tmp_path), str(descriptor_path))

        assert resolved.path == str(descriptor_path)
        assert resolved.meta is None

    def test_explicit_manifest_template_uses_margo_yaml_context(self, project: Path) -> None:
        """Should load margo.yaml for the render context when --manifest is a template."""
        template_path = project / "margo" / "custom.yaml.jinja"
        template_path.write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        resolved = resolve_descriptor(str(project), str(template_path))
        try:
            assert resolved.rendered is True
            assert resolved.meta is not None
            assert "id: hello-world" in Path(resolved.path).read_text(encoding="utf-8")
        finally:
            Path(resolved.path).unlink()

    def test_missing_explicit_manifest_raises(self, project: Path) -> None:
        """Should name the missing manifest path."""
        with raises(ValueError, match="Application description not found:"):
            resolve_descriptor(str(project), str(project / "margo" / "absent.yaml"))

    def test_both_descriptor_forms_present_raises(self, project: Path) -> None:
        """Should raise build's both-files-present error."""
        (project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")
        (project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        with raises(ValueError, match=r"Both app.yaml.jinja and app.yaml found"):
            resolve_descriptor(str(project))

    def test_no_descriptor_raises(self, project: Path) -> None:
        """Should raise when neither descriptor form exists."""
        with raises(ValueError, match=r"No app.yaml or app.yaml.jinja found"):
            resolve_descriptor(str(project))

    def test_missing_margo_yaml_raises(self, tmp_path: Path) -> None:
        """Should raise the metadata loader's margo.yaml error."""
        with raises(ValueError, match=r"margo.yaml not found"):
            resolve_descriptor(str(tmp_path))


class TestSchemaOverride:
    """Tests for the --schema override path."""

    def test_custom_schema_is_used(self, project: Path, tmp_path: Path) -> None:
        """Should validate against the provided schema instead of the vendored one."""
        (project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")
        custom_schema = tmp_path / "custom.linkml.yaml"
        custom_schema.write_text(
            """
id: https://example.org/custom
name: custom
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/custom/
default_prefix: ex
imports:
  - linkml:types
classes:
  ApplicationDescription:
    attributes:
      mandatoryThing:
        range: string
        required: true
""",
            encoding="utf-8",
        )

        result = verify(project_dir=str(project), schema_path=str(custom_schema))

        assert result.passed is False
        assert any("'mandatoryThing' is a required property" in finding.message for finding in result.schema_a_results)
