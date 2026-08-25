"""Integration tests for the curated recommended schema (Schema B).

Runs the real `margo-recommended.linkml.yaml` through the same runner Schema A uses, so the
overlay mechanism (import + `is_a` subclasses) is covered, not just the recommendation content.
"""

from collections.abc import Sequence
from pathlib import Path

from pytest import fixture

from margot.domain.validation import Severity, ValidationFinding
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


class TestOverlayMechanism:
    """The import + is_a overlay itself."""

    def test_schema_b_ships_next_to_schema_a(self) -> None:
        """Should resolve to a real file — the relative LinkML import depends on it."""
        assert Path(SCHEMA_B_PATH).is_file()
        assert Path(SCHEMA_B_PATH).name == "margo-recommended.linkml.yaml"
        assert (Path(SCHEMA_B_PATH).parent / "application-description.linkml.yaml").is_file()

    def test_spec_classes_are_reachable_through_the_import(self, compliant: str, tmp_path: Path) -> None:
        """Should still enforce Schema A's own constraints, proving the import resolved.

        `id` carries a lowercase pattern declared only in Schema A. A shadowed or unresolved
        import would silently drop it instead of reporting the breach.
        """
        findings = _findings(compliant.replace("id: hello-world", "id: Hello_World"), tmp_path)

        assert [finding.field_path for finding in findings] == ["/id"]
        assert _messages(findings, Severity.ERROR) == ["'Hello_World' does not match '^[a-z0-9-]{1,200}$'"]
