"""Integration tests for the curated recommended schema (Schema B).

Runs the real `margo-recommended.linkml.yaml` through the same runner Schema A uses, so the
schema's own required-field checks and recommendation content are both covered, and it is a
standalone schema — no import of, or subclass relationship to, Schema A.
"""

from collections.abc import Sequence
from pathlib import Path

from pytest import fixture

from margot.domain.validation import Severity, ValidationFinding
from margot.infra.filesystem import load_yaml
from margot.schemas import SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS
from margot.validation.linkml_runner import run_validation

COMPLIANT_APP_YAML = """apiVersion: application.margo.org/v1alpha1
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


def _findings(descriptor: str, tmp_path: Path) -> list[ValidationFinding]:
    """Validate a descriptor against the real Schema B."""
    path = tmp_path / "app.yaml"
    path.write_text(descriptor, encoding="utf-8")
    return run_validation(str(path), SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS)


def _messages(findings: Sequence[ValidationFinding], severity: Severity) -> list[str]:
    """Return the messages of every finding with the given severity."""
    return [finding.message for finding in findings if finding.severity is severity]


@fixture
def compliant() -> str:
    """A descriptor satisfying every Schema B recommendation."""
    return COMPLIANT_APP_YAML


class TestCompliantDescriptor:
    """A descriptor meeting every recommendation is clean."""

    def test_compliant_descriptor_has_no_findings(self, compliant: str, tmp_path: Path) -> None:
        """Should report nothing at all — the overlay adds no false positives."""
        assert _findings(compliant, tmp_path) == []

    def test_vendor_extensions_do_not_false_fail(self, compliant: str, tmp_path: Path) -> None:
        """Should accept x-placeholder-extensions at profile and component level too."""
        descriptor = compliant.replace(
            "    components:\n",
            "    x-placeholder-extensions:\n      vendor-acme:\n        profileHint: fast\n    components:\n",
        )

        assert _findings(descriptor, tmp_path) == []


class TestRecommendedSlots:
    """Optional-in-the-spec fields that Schema B recommends."""

    def test_missing_description_warns(self, compliant: str, tmp_path: Path) -> None:
        """Should warn on metadata.description, never error."""
        findings = _findings(compliant.replace("  description: A sample application\n", ""), tmp_path)

        assert _messages(findings, Severity.ERROR) == []
        assert findings == [
            ValidationFinding(
                "/metadata",
                "Slot 'description' is recommended on class 'RecommendedMetadata'",
                Severity.WARNING,
            )
        ]

    def test_missing_catalog_application_slots_warn(self, compliant: str, tmp_path: Path) -> None:
        """Should warn once per missing icon / descriptionFile / releaseNotes."""
        descriptor = compliant.replace(
            "      icon: https://example.com/icon.png\n      descriptionFile: README.md\n      releaseNotes: NOTES.md\n",
            "      site: https://example.com\n",
        )
        findings = _findings(descriptor, tmp_path)

        assert _messages(findings, Severity.ERROR) == []
        assert {finding.field_path for finding in findings} == {"/metadata/catalog/application"}
        assert _messages(findings, Severity.WARNING) == [
            "Slot 'descriptionFile' is recommended on class 'RecommendedApplicationMetadata'",
            "Slot 'icon' is recommended on class 'RecommendedApplicationMetadata'",
            "Slot 'releaseNotes' is recommended on class 'RecommendedApplicationMetadata'",
        ]

    def test_missing_catalog_application_block_warns(self, compliant: str, tmp_path: Path) -> None:
        """Should warn on the application block itself, since its own slots become unreachable."""
        descriptor = compliant.replace(
            "    application:\n"
            "      icon: https://example.com/icon.png\n"
            "      descriptionFile: README.md\n"
            "      releaseNotes: NOTES.md\n",
            "",
        )
        findings = _findings(descriptor, tmp_path)

        assert _messages(findings, Severity.ERROR) == []
        assert _messages(findings, Severity.WARNING) == ["Slot 'application' is recommended on class 'RecommendedCatalog'"]

    def test_missing_author_warns(self, compliant: str, tmp_path: Path) -> None:
        """Should warn on catalog.author, which the spec leaves optional."""
        descriptor = compliant.replace(
            "    author:\n      - name: Jane Doe\n        email: jane@example.com\n",
            "",
        )
        findings = _findings(descriptor, tmp_path)

        assert _messages(findings, Severity.ERROR) == []
        assert _messages(findings, Severity.WARNING) == ["Slot 'author' is recommended on class 'RecommendedCatalog'"]


class TestCardinality:
    """Cardinality tightened beyond the spec, which accepts empty lists."""

    def test_empty_deployment_profiles_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR: minimum_cardinality becomes a JSON Schema minItems."""
        descriptor = compliant[: compliant.index("deploymentProfiles:")] + "deploymentProfiles: []\n"
        findings = _findings(descriptor, tmp_path)

        assert findings == [ValidationFinding("/deploymentProfiles", "[] should be non-empty", Severity.ERROR)]

    def test_empty_components_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR on the offending profile's components slot."""
        descriptor = compliant[: compliant.index("    components:")] + "    components: []\n"
        findings = _findings(descriptor, tmp_path)

        assert findings == [ValidationFinding("/deploymentProfiles/0/components", "[] should be non-empty", Severity.ERROR)]

    def test_absent_deployment_profiles_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the inherited required-property ERROR when the slot is absent entirely."""
        descriptor = compliant[: compliant.index("deploymentProfiles:")]
        findings = _findings(descriptor, tmp_path)

        assert _messages(findings, Severity.ERROR) == ["'deploymentProfiles' is a required property"]


class TestRequiredFields:
    """Schema B's own required-field enforcement — no longer inherited from Schema A.

    Covers the top-level required set plus the required chain reachable from it, per the
    rendered spec (see the decision comment at the top of margo-recommended.linkml.yaml).
    """

    def test_missing_api_version_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for apiVersion."""
        descriptor = "\n".join(line for line in compliant.splitlines() if not line.startswith("apiVersion:"))
        findings = _findings(descriptor, tmp_path)

        assert _messages(findings, Severity.ERROR) == ["'apiVersion' is a required property"]

    def test_missing_id_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for id."""
        descriptor = "\n".join(line for line in compliant.splitlines() if not line.startswith("id:"))
        findings = _findings(descriptor, tmp_path)

        assert _messages(findings, Severity.ERROR) == ["'id' is a required property"]

    def test_missing_metadata_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for metadata."""
        descriptor = compliant[: compliant.index("metadata:")] + compliant[compliant.index("deploymentProfiles:") :]
        findings = _findings(descriptor, tmp_path)

        assert _messages(findings, Severity.ERROR) == ["'metadata' is a required property"]

    def test_missing_metadata_name_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for metadata.name."""
        descriptor = compliant.replace("  name: Hello World\n", "")
        findings = _findings(descriptor, tmp_path)

        assert findings == [ValidationFinding("/metadata", "'name' is a required property", Severity.ERROR)]

    def test_missing_metadata_version_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for metadata.version."""
        descriptor = compliant.replace("  version: 1.0.0\n", "")
        findings = _findings(descriptor, tmp_path)

        assert findings == [ValidationFinding("/metadata", "'version' is a required property", Severity.ERROR)]

    def test_missing_organization_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for catalog.organization."""
        descriptor = compliant[: compliant.index("    organization:")] + compliant[compliant.index("deploymentProfiles:") :]
        findings = _findings(descriptor, tmp_path)

        assert findings == [ValidationFinding("/metadata/catalog", "'organization' is a required property", Severity.ERROR)]

    def test_missing_organization_name_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for organization[].name."""
        descriptor = compliant.replace("      - name: Example Corp\n", "      -")
        findings = _findings(descriptor, tmp_path)

        assert _messages(findings, Severity.ERROR) == ["'name' is a required property"]

    def test_missing_deployment_profile_type_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for deploymentProfiles[].type."""
        descriptor = compliant.replace("  - type: compose\n    id: default\n", "  - id: default\n")
        findings = _findings(descriptor, tmp_path)

        assert findings == [ValidationFinding("/deploymentProfiles/0", "'type' is a required property", Severity.ERROR)]

    def test_missing_deployment_profile_id_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for deploymentProfiles[].id."""
        descriptor = compliant.replace("    id: default\n", "")
        findings = _findings(descriptor, tmp_path)

        assert findings == [ValidationFinding("/deploymentProfiles/0", "'id' is a required property", Severity.ERROR)]

    def test_missing_component_name_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for components[].name."""
        descriptor = compliant.replace(
            "      - name: hello-world-compose\n        properties:",
            "      - properties:",
        )
        findings = _findings(descriptor, tmp_path)

        assert findings == [
            ValidationFinding("/deploymentProfiles/0/components/0", "'name' is a required property", Severity.ERROR)
        ]

    def test_missing_component_properties_is_an_error(self, compliant: str, tmp_path: Path) -> None:
        """Should report the required-property ERROR for components[].properties."""
        descriptor = compliant.replace(
            "        properties:\n          packageLocation: https://example.com/compose.tar.gz\n",
            "",
        )
        findings = _findings(descriptor, tmp_path)

        assert findings == [
            ValidationFinding("/deploymentProfiles/0/components/0", "'properties' is a required property", Severity.ERROR)
        ]

    def test_fully_compliant_descriptor_has_no_required_field_errors(self, compliant: str, tmp_path: Path) -> None:
        """Should report zero ERRORs on a descriptor satisfying every required field."""
        findings = _findings(compliant, tmp_path)

        assert _messages(findings, Severity.ERROR) == []


class TestStandaloneSchema:
    """Schema B does not import or subclass Schema A — it is fully self-contained."""

    def test_schema_b_ships_next_to_schema_a(self) -> None:
        """Should resolve to a real file, independent of whether Schema A is present."""
        assert Path(SCHEMA_B_PATH).is_file()
        assert Path(SCHEMA_B_PATH).name == "margo-recommended.linkml.yaml"

    def test_schema_b_does_not_import_schema_a(self) -> None:
        """Should carry no `imports:` reference to the vendored upstream schema.

        Regression guard for the coupling this schema was redesigned to remove: an edit to
        application-description.linkml.yaml must never change what Schema B enforces. Only
        the `imports:` block is checked — comments are free to reference Schema A by name to
        explain the design decision.
        """
        schema = load_yaml(SCHEMA_B_PATH)
        assert isinstance(schema, dict)

        assert "application-description.linkml" not in schema.get("imports", [])

    def test_schema_a_id_pattern_is_not_inherited(self, compliant: str, tmp_path: Path) -> None:
        """Should accept a value Schema A's `id` pattern would reject.

        Schema A constrains `id` to `^[a-z0-9-]{1,200}$`; Schema B only requires the field to
        be present. Proves the two schemas are independent, not that Schema B is laxer by
        design intent — value-level rules are follow-up work (see the decision comment).
        """
        findings = _findings(compliant.replace("id: hello-world", "id: Hello_World"), tmp_path)

        assert findings == []
