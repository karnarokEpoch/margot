"""Unit tests for validation/linkml_runner.py against a minimal fixture schema."""

from pathlib import Path
from types import SimpleNamespace

from linkml.validator.report import Severity as LinkmlSeverity
from pytest import fixture

from margot.domain.validation import Severity
from margot.validation.linkml_runner import _to_finding, run_validation, strip_extension_slots

MINIMAL_SCHEMA = """
id: https://example.org/minimal
name: minimal
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/minimal/
default_prefix: ex
imports:
  - linkml:types

classes:
  Widget:
    tree_root: true
    attributes:
      name:
        range: string
        required: true
      color:
        range: string
        recommended: true
      size:
        range: integer
      tags:
        range: string
        multivalued: true
        maximum_cardinality: 2
      parts:
        range: Part
        multivalued: true
        inlined: true
        inlined_as_list: false
        maximum_cardinality: 1

  Part:
    attributes:
      name:
        range: string
        identifier: true
      weight:
        range: integer
"""


@fixture
def schema_path(tmp_path: Path) -> str:
    """Write the minimal fixture schema and return its path."""
    path = tmp_path / "minimal.linkml.yaml"
    path.write_text(MINIMAL_SCHEMA, encoding="utf-8")
    return str(path)


def write_data(tmp_path: Path, content: str, name: str = "data.yaml") -> str:
    """Write an instance document and return its path."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


class TestRunValidationPasses:
    """Cases that produce no findings."""

    def test_all_pass(self, tmp_path: Path, schema_path: str) -> None:
        """Should report nothing for a fully valid instance."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\nsize: 3\ntags:\n  - a\n  - b\n")

        assert run_validation(data_path, schema_path, "Widget") == []

    def test_optional_slots_may_be_absent(self, tmp_path: Path, schema_path: str) -> None:
        """Should report nothing when only optional non-recommended slots are missing."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\n")

        assert run_validation(data_path, schema_path, "Widget") == []

    def test_target_class_can_be_inferred(self, tmp_path: Path, schema_path: str) -> None:
        """Should infer the tree_root class when no target class is given."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\n")

        assert run_validation(data_path, schema_path) == []


class TestRunValidationErrors:
    """Cases that produce ERROR findings."""

    def test_single_error_for_missing_required_slot(self, tmp_path: Path, schema_path: str) -> None:
        """Should report one ERROR naming the missing required slot."""
        data_path = write_data(tmp_path, "color: red\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert len(findings) == 1
        assert findings[0].severity is Severity.ERROR
        assert "'name' is a required property" in findings[0].message
        assert findings[0].field_path == "/"

    def test_error_for_wrong_type(self, tmp_path: Path, schema_path: str) -> None:
        """Should report an ERROR with the offending field path."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\nsize: not-a-number\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]
        assert findings[0].field_path == "/size"

    def test_error_for_unexpected_field(self, tmp_path: Path, schema_path: str) -> None:
        """Should report an ERROR for an undeclared field (closed=True)."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\nnope: 1\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]
        assert "Additional properties are not allowed" in findings[0].message

    def test_error_for_list_maximum_cardinality_breach(self, tmp_path: Path, schema_path: str) -> None:
        """Should report exactly one ERROR — linkml's JSON Schema enforces maxItems."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\ntags:\n  - a\n  - b\n  - c\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]
        assert "is too long" in findings[0].message
        assert findings[0].field_path == "/tags"

    def test_error_for_map_maximum_cardinality_breach(self, tmp_path: Path, schema_path: str) -> None:
        """Should report the map-form breach that linkml's JSON Schema misses."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\nparts:\n  a:\n    weight: 1\n  b:\n    weight: 2\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]
        assert "allows at most 1 value(s), got 2" in findings[0].message
        assert findings[0].field_path == "/parts"

    def test_map_within_maximum_cardinality_passes(self, tmp_path: Path, schema_path: str) -> None:
        """Should report nothing when a map-form slot stays within its maximum."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\nparts:\n  a:\n    weight: 1\n")

        assert run_validation(data_path, schema_path, "Widget") == []

    def test_missing_file_is_a_single_error(self, tmp_path: Path, schema_path: str) -> None:
        """Should report a hard ERROR instead of raising for an absent document."""
        findings = run_validation(str(tmp_path / "absent.yaml"), schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]
        assert "File not found" in findings[0].message

    def test_malformed_yaml_is_a_single_error(self, tmp_path: Path, schema_path: str) -> None:
        """Should report a hard ERROR for an unparseable document."""
        data_path = write_data(tmp_path, "name: [unclosed\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]
        assert "is not valid YAML" in findings[0].message

    def test_non_mapping_root_is_a_single_error(self, tmp_path: Path, schema_path: str) -> None:
        """Should report a hard ERROR when the document root is not a mapping."""
        data_path = write_data(tmp_path, "- one\n- two\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]
        assert findings[0].message == "Expected a YAML mapping at the document root."

    def test_empty_document_is_a_single_error(self, tmp_path: Path, schema_path: str) -> None:
        """Should report a hard ERROR for an empty document."""
        data_path = write_data(tmp_path, "")

        findings = run_validation(data_path, schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]

    def test_unknown_target_class_is_a_single_error(self, tmp_path: Path, schema_path: str) -> None:
        """Should report a hard ERROR when the target class is absent from the schema."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\n")

        findings = run_validation(data_path, schema_path, "Gadget")

        assert [finding.severity for finding in findings] == [Severity.ERROR]
        assert "Schema could not be applied" in findings[0].message


class TestRunValidationWarnings:
    """Cases that produce WARNING findings only."""

    def test_warning_only_for_missing_recommended_slot(self, tmp_path: Path, schema_path: str) -> None:
        """Should report a WARNING, never an ERROR, for a missing recommended slot."""
        data_path = write_data(tmp_path, "name: bolt\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert [finding.severity for finding in findings] == [Severity.WARNING]
        assert "'color' is recommended" in findings[0].message
        assert findings[0].field_path == "/"


class TestStripExtensionSlots:
    """Tests for the x-placeholder-extensions pre-processing step."""

    def test_removes_extension_key_at_every_level(self) -> None:
        """Should drop the extension slot from nested mappings and lists."""
        data = {
            "id": "app",
            "x-placeholder-extensions": {"vendor": {"a": 1}},
            "deploymentProfiles": [
                {
                    "id": "default",
                    "x-placeholder-extensions": {"vendor": {"b": 2}},
                    "components": [{"name": "c", "x-placeholder-extensions": {"vendor": {"c": 3}}}],
                }
            ],
        }

        assert strip_extension_slots(data) == {
            "id": "app",
            "deploymentProfiles": [{"id": "default", "components": [{"name": "c"}]}],
        }

    def test_leaves_other_content_untouched(self) -> None:
        """Should return equal data when no extension slot is present."""
        data = {"id": "app", "tags": ["a", "b"], "size": 1, "flag": None}

        assert strip_extension_slots(data) == data

    def test_passes_scalars_through(self) -> None:
        """Should return scalars unchanged."""
        assert strip_extension_slots("text") == "text"
        assert strip_extension_slots(7) == 7


class TestScalarMapEntries:
    """Cardinality checking must tolerate map entries that are not mappings."""

    def test_scalar_map_entries_still_report_cardinality(self, tmp_path: Path, schema_path: str) -> None:
        """Should report the map-form breach even when entries are scalars."""
        data_path = write_data(tmp_path, "name: bolt\ncolor: red\nparts:\n  a: 1\n  b: 2\n")

        findings = run_validation(data_path, schema_path, "Widget")

        assert any("allows at most 1 value(s), got 2" in finding.message for finding in findings)


class TestFindingMapping:
    """Tests for the linkml-result → ValidationFinding mapping."""

    def test_message_without_location_falls_back_to_source_path(self) -> None:
        """Should take the field path from the jsonschema error when the message has none."""
        result = SimpleNamespace(
            message="something went wrong",
            severity=LinkmlSeverity.ERROR,
            source=SimpleNamespace(absolute_path=["metadata", "catalog", 0]),
        )

        finding = _to_finding(result)

        assert finding.field_path == "/metadata/catalog/0"
        assert finding.message == "something went wrong"

    def test_message_without_location_and_without_source(self) -> None:
        """Should fall back to the document root when no location is available."""
        result = SimpleNamespace(message="opaque failure", severity=LinkmlSeverity.WARN, source=None)

        finding = _to_finding(result)

        assert finding.field_path == "/"
        assert finding.severity is Severity.WARNING

    def test_fatal_maps_to_error(self) -> None:
        """Should treat linkml FATAL as a margot ERROR."""
        result = SimpleNamespace(message="fatal problem in /id", severity=LinkmlSeverity.FATAL, source=None)

        finding = _to_finding(result)

        assert finding.severity is Severity.ERROR
        assert finding.field_path == "/id"

    def test_info_maps_to_info(self) -> None:
        """Should keep informational results informational."""
        result = SimpleNamespace(message="note in /metadata", severity=LinkmlSeverity.INFO, source=None)

        assert _to_finding(result).severity is Severity.INFO
