"""Unit tests for validation/linkml_runner.py against a minimal fixture schema."""

from pathlib import Path
from types import SimpleNamespace

from linkml.validator.report import Severity as LinkmlSeverity
from pytest import fixture

from margot.domain.validation import Severity, ValidationFinding
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

# Mirrors the shape that triggered the bug in the real spec schema: a multivalued slot whose
# range is a parent class with subclasses, which linkml compiles to an `anyOf` over one
# candidate schema per class. A failure anywhere inside such a value makes jsonschema report
# "<whole instance repr> is not valid under any of the given schemas". `kind` is the
# discriminator — patterned on the parent, pinned by `equals_string` on each subclass — so a
# bad `kind` fails every branch on that one slot, exactly like `deploymentProfiles[].type`.
POLYMORPHIC_SCHEMA = """
id: https://example.org/polymorphic
name: polymorphic
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/polymorphic/
default_prefix: ex
imports:
  - linkml:types

classes:
  Machine:
    tree_root: true
    attributes:
      name:
        range: string
        required: true
      profiles:
        range: Profile
        multivalued: true
        inlined: true
        inlined_as_list: true

  Profile:
    attributes:
      kind:
        range: string
        required: true
        pattern: "^(helm|compose)$"
      settings:
        range: Settings
        required: true

  HelmProfile:
    is_a: Profile
    slot_usage:
      kind:
        equals_string: "helm"

  ComposeProfile:
    is_a: Profile
    slot_usage:
      kind:
        equals_string: "compose"

  Settings:
    attributes:
      revision:
        range: string
      wait:
        range: boolean
      packageLocation:
        range: string
      keyLocation:
        range: string
"""


@fixture
def schema_path(tmp_path: Path) -> str:
    """Write the minimal fixture schema and return its path."""
    path = tmp_path / "minimal.linkml.yaml"
    path.write_text(MINIMAL_SCHEMA, encoding="utf-8")
    return str(path)


@fixture
def polymorphic_schema_path(tmp_path: Path) -> str:
    """Write the polymorphic fixture schema and return its path."""
    path = tmp_path / "polymorphic.linkml.yaml"
    path.write_text(POLYMORPHIC_SCHEMA, encoding="utf-8")
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


class TestPolymorphicSlotErrors:
    """A oneOf/anyOf failure must be summarized, not dumped as an instance repr."""

    def _finding(self, tmp_path: Path, schema_path: str, data: str) -> ValidationFinding:
        findings = run_validation(write_data(tmp_path, data), schema_path, "Machine")
        assert len(findings) == 1
        return findings[0]

    def test_summary_replaces_the_instance_dump(self, tmp_path: Path, polymorphic_schema_path: str) -> None:
        """Should report the specific failing field instead of jsonschema's instance repr."""
        finding = self._finding(
            tmp_path,
            polymorphic_schema_path,
            "name: press\nprofiles:\n  - kind: compose\n    settings:\n      wait: not-a-bool\n",
        )

        assert finding.severity is Severity.ERROR
        assert finding.field_path == "/profiles/0"
        assert "is not valid under any of the given schemas" not in finding.message
        assert "{'" not in finding.message
        assert "settings/wait" in finding.message
        assert "'not-a-bool' is not of type 'boolean'" in finding.message

    def test_differing_paths_keep_a_header_without_schema_jargon(self, tmp_path: Path, polymorphic_schema_path: str) -> None:
        """Should head a multi-field failure with plain wording, not "candidate schemas"."""
        finding = self._finding(
            tmp_path,
            polymorphic_schema_path,
            "name: press\nprofiles:\n  - kind: compose\n    settings:\n      wait: not-a-bool\n",
        )

        assert finding.message.startswith("no matching schema — possible causes: ")
        assert "none of" not in finding.message
        assert "candidate schemas matched" not in finding.message

    def test_shared_path_is_promoted_out_of_the_reasons(self, tmp_path: Path, polymorphic_schema_path: str) -> None:
        """Should name a bad discriminator once, in the path, then list only the reasons."""
        finding = self._finding(
            tmp_path,
            polymorphic_schema_path,
            "name: press\nprofiles:\n  - kind: quadlet\n    settings:\n      wait: true\n",
        )

        assert finding.severity is Severity.ERROR
        assert finding.field_path == "/profiles/0/kind"
        assert "{'" not in finding.message
        assert "none of" not in finding.message
        assert "candidate schemas matched" not in finding.message
        assert "(at " not in finding.message
        assert finding.message.count("kind") == 0

    def test_shared_path_summary_keeps_every_distinct_reason(self, tmp_path: Path, polymorphic_schema_path: str) -> None:
        """Should still carry the pattern mismatch and both rejected constants."""
        finding = self._finding(
            tmp_path,
            polymorphic_schema_path,
            "name: press\nprofiles:\n  - kind: quadlet\n    settings:\n      wait: true\n",
        )

        assert "'quadlet' does not match '^(helm|compose)$'" in finding.message
        assert "'helm' was expected" in finding.message
        assert "'compose' was expected" in finding.message

    def test_summary_stays_short_enough_for_one_ci_line(self, tmp_path: Path, polymorphic_schema_path: str) -> None:
        """Should stay far below the raw instance dump, whose size grows with the instance."""
        # Only `wait` is invalid; the other slots are valid but bulky, so jsonschema's own
        # message (a repr of the whole profile) is >600 chars here while the summary is not
        # affected by them at all. 300 chars is the bound: enough for the three reasons the
        # summary may list, short enough for a single grep-able `SEVERITY path: message` line.
        location = "https://example.com/some/quite/long/artifact/path/package-1.0.0.tar.gz"
        data = (
            "name: press\n"
            "profiles:\n"
            "  - kind: compose\n"
            "    settings:\n"
            "      wait: not-a-bool\n"
            f"      packageLocation: {location}\n"
            f"      keyLocation: {location}.sig\n"
        )

        finding = self._finding(tmp_path, polymorphic_schema_path, data)

        assert location not in finding.message
        assert len(finding.message) < 300

    def test_summary_deduplicates_and_caps_reasons(self, tmp_path: Path, polymorphic_schema_path: str) -> None:
        """Should list at most three distinct reasons and count the remainder."""
        data = (
            "name: press\nprofiles:\n  - kind: nope\n    settings:\n      wait: not-a-bool\n      revision: 7\n      extra: 1\n"
        )

        finding = self._finding(tmp_path, polymorphic_schema_path, data)

        assert finding.message.count("(at ") == 3
        assert " more" in finding.message

    def test_non_polymorphic_error_message_is_untouched(self, tmp_path: Path, polymorphic_schema_path: str) -> None:
        """Should pass a plain single error through with no summary wrapper."""
        finding = self._finding(tmp_path, polymorphic_schema_path, "profiles: []\n")

        assert finding.message == "'name' is a required property"
        assert "no matching schema" not in finding.message


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

    def test_alternatives_without_context_pass_through(self) -> None:
        """Should leave a oneOf error alone when it carries no sub-errors to summarize."""
        result = SimpleNamespace(
            message="valid under each of the given schemas",
            severity=LinkmlSeverity.ERROR,
            source=SimpleNamespace(validator="oneOf", context=[], absolute_path=["id"]),
        )

        finding = _to_finding(result)

        assert finding.message == "valid under each of the given schemas"
        assert finding.field_path == "/id"

    def test_long_sub_message_is_truncated(self) -> None:
        """Should cap an individual reason so a nested instance repr cannot leak in whole."""
        result = SimpleNamespace(
            message="ignored",
            severity=LinkmlSeverity.ERROR,
            source=SimpleNamespace(
                validator="anyOf",
                context=[SimpleNamespace(validator="type", absolute_path=["settings"], message="x" * 400)],
                absolute_path=[],
            ),
        )

        finding = _to_finding(result)

        assert finding.field_path == "/settings"
        assert finding.message == f"{'x' * 120}..."

    def test_reasons_at_the_failure_root_get_no_path_prefix(self) -> None:
        """Should render a sub-error with no sub-path as the bare reason, on the failure's path."""
        result = SimpleNamespace(
            message="ignored",
            severity=LinkmlSeverity.ERROR,
            source=SimpleNamespace(
                validator="anyOf",
                context=[SimpleNamespace(validator="type", message="1 is not of type 'string'")],
                absolute_path=["a"],
            ),
        )

        finding = _to_finding(result)

        assert finding.field_path == "/a"
        assert finding.message == "1 is not of type 'string'"

    def test_shared_path_is_appended_to_a_root_field_path(self) -> None:
        """Should not double the separator when the failure itself sits at the document root."""
        result = SimpleNamespace(
            message="ignored",
            severity=LinkmlSeverity.ERROR,
            source=SimpleNamespace(
                validator="oneOf",
                context=[SimpleNamespace(validator="pattern", absolute_path=["kind"], message="bad kind")],
                absolute_path=[],
            ),
        )

        assert _to_finding(result).field_path == "/kind"
