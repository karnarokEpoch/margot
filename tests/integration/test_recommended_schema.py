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

COMPLIANT_APP_YAML = """apiVersion: v1
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
          repository: oci://example.com/compose/hello-world
          revision: 1.0.0
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
            "        properties:\n          repository: oci://example.com/compose/hello-world\n          revision: 1.0.0\n",
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


class TestValueLevelChecks:
    """Pattern/value constraints added on top of the presence/cardinality checks above."""

    def test_apiversion_accepts_bare_v1(self, compliant: str, tmp_path: Path) -> None:
        """Should accept the bare `v1` form margot's own fixtures use."""
        assert _findings(compliant, tmp_path) == []

    def test_apiversion_accepts_a_pre_release_suffix(self, compliant: str, tmp_path: Path) -> None:
        """Should accept `v<N>alpha<N>`/`v<N>beta<N>` suffixes on the bare version."""
        descriptor = compliant.replace("apiVersion: v1\n", "apiVersion: v2alpha3\n")

        assert _findings(descriptor, tmp_path) == []

    def test_apiversion_rejects_the_fully_qualified_form(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR for `application.margo.org/v1alpha1` — no longer a valid shape."""
        descriptor = compliant.replace("apiVersion: v1\n", "apiVersion: application.margo.org/v1alpha1\n")
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/apiVersion"]
        assert _messages(findings, Severity.ERROR) != []

    def test_apiversion_rejects_garbage(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR for a value matching neither known shape."""
        descriptor = compliant.replace("apiVersion: v1\n", "apiVersion: banana\n")
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/apiVersion"]
        assert _messages(findings, Severity.ERROR) != []

    def test_kind_rejects_wrong_value(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR when kind names something other than ApplicationDescription."""
        descriptor = compliant.replace("kind: ApplicationDescription\n", "kind: Something\n")
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/kind"]
        assert _messages(findings, Severity.ERROR) != []

    def test_id_rejects_uppercase_and_underscores(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR for an id outside the lowercase/digit/dash charset."""
        descriptor = compliant.replace("id: hello-world\n", "id: Hello_World\n")
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/id"]
        assert _messages(findings, Severity.ERROR) != []

    def test_id_accepts_a_single_dash_id(self, compliant: str, tmp_path: Path) -> None:
        """Should accept the un-namespaced ids already used across the fixture suite.

        The ≥3-dash domain-namespacing convention (e.g. `com-example-mosquitto`) is
        documentation guidance only, not an enforced pattern — see the slot description.
        """
        assert _findings(compliant, tmp_path) == []

    def test_organization_site_rejects_a_non_url(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR when organization.site is not an http(s) URL."""
        descriptor = compliant.replace("        site: https://example.com\n", "        site: example.com\n")
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/metadata/catalog/organization/0/site"]
        assert _messages(findings, Severity.ERROR) != []

    def test_organization_site_accepts_http_and_https(self, compliant: str, tmp_path: Path) -> None:
        """Should accept both http:// and https:// forms."""
        assert _findings(compliant, tmp_path) == []
        assert _findings(compliant.replace("https://example.com", "http://example.com"), tmp_path) == []

    def test_repository_requires_oci_scheme(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR when repository does not use the oci:// scheme."""
        descriptor = compliant.replace(
            "          repository: oci://example.com/compose/hello-world\n",
            "          repository: https://example.com/compose/hello-world\n",
        )
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/deploymentProfiles/0/components/0/properties/repository"]
        assert _messages(findings, Severity.ERROR) != []

    def test_repository_accepts_oci_scheme(self, compliant: str, tmp_path: Path) -> None:
        """Should accept a well-formed oci:// reference."""
        assert _findings(compliant, tmp_path) == []

    def test_package_location_is_banned(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR when packageLocation is present at all.

        `packageLocation`/`keyLocation` are not declared as attributes on
        RecommendedComponentProperties, so under `closed=True` they surface as an unknown
        property — see the class description.
        """
        descriptor = compliant.replace(
            "          repository: oci://example.com/compose/hello-world\n          revision: 1.0.0\n",
            "          packageLocation: https://example.com/compose.tar.gz\n",
        )
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/deploymentProfiles/0/components/0/properties"]
        assert _messages(findings, Severity.ERROR) != []

    def test_key_location_is_banned(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR when keyLocation is present at all. See packageLocation above."""
        descriptor = compliant.replace(
            "          revision: 1.0.0\n",
            "          revision: 1.0.0\n          keyLocation: https://example.com/compose.tar.gz.sig\n",
        )
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/deploymentProfiles/0/components/0/properties"]
        assert _messages(findings, Severity.ERROR) != []

    def test_timeout_accepts_the_documented_minutes_and_seconds_format(self, compliant: str, tmp_path: Path) -> None:
        """Should accept the "##m##s" format the spec documents."""
        descriptor = compliant.replace(
            "          revision: 1.0.0\n",
            "          revision: 1.0.0\n          timeout: 8m30s\n",
        )

        assert _findings(descriptor, tmp_path) == []

    def test_timeout_accepts_a_seconds_only_format(self, compliant: str, tmp_path: Path) -> None:
        """Should accept "##s" with no minutes component — minutes are optional."""
        descriptor = compliant.replace(
            "          revision: 1.0.0\n",
            "          revision: 1.0.0\n          timeout: 90s\n",
        )

        assert _findings(descriptor, tmp_path) == []

    def test_timeout_rejects_a_bare_number(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR for a timeout missing the trailing seconds unit."""
        descriptor = compliant.replace(
            "          revision: 1.0.0\n",
            "          revision: 1.0.0\n          timeout: 90\n",
        )
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/deploymentProfiles/0/components/0/properties/timeout"]
        assert _messages(findings, Severity.ERROR) != []

    def test_pointer_accepts_helm_dot_notation(self, compliant: str, tmp_path: Path) -> None:
        """Should accept a Helm-style values.yaml dot path."""
        descriptor = _with_target(compliant, "image.tag")

        assert _findings(descriptor, tmp_path) == []

    def test_pointer_accepts_compose_env_var_name(self, compliant: str, tmp_path: Path) -> None:
        """Should accept a Compose-style UPPER_SNAKE_CASE environment variable name."""
        descriptor = _with_target(compliant, "MQTT_PORT")

        assert _findings(descriptor, tmp_path) == []

    def test_pointer_rejects_whitespace_and_shell_metacharacters(self, compliant: str, tmp_path: Path) -> None:
        """Should report an ERROR for a pointer that is not identifier-shaped.

        Deliberately light-touch: Helm dot-paths and Compose env var names cannot be told
        apart from the string alone (see the slot description), so this only rejects
        obviously-wrong shapes rather than picking one convention.
        """
        descriptor = _with_target(compliant, "$(rm -rf /)")
        findings = _findings(descriptor, tmp_path)

        assert [f.field_path for f in findings] == ["/parameters/greeting/targets/0/pointer"]
        assert _messages(findings, Severity.ERROR) != []


def _with_target(compliant: str, pointer: str) -> str:
    """Return `compliant` with a top-level `parameters` entry targeting the given pointer."""
    return compliant.replace(
        "x-placeholder-extensions:",
        f"parameters:\n  greeting:\n    value: hi\n    targets:\n      - pointer: {pointer}\n"
        '        components: ["hello-world-compose"]\nx-placeholder-extensions:',
    )


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

    def test_schema_b_defines_its_own_id_pattern(self, compliant: str, tmp_path: Path) -> None:
        """Should reject a value against Schema B's own `id` pattern, not an inherited one.

        Schema A and Schema B both constrain `id` to `^[a-z0-9-]{1,200}$`, but Schema B's
        rule is declared directly on `RecommendedApplicationDescription` — this schema has no
        `imports:`/`is_a:` relationship to Schema A at all (see the two tests above). The
        matching shape is coincidence of intent, not inheritance.
        """
        findings = _findings(compliant.replace("id: hello-world", "id: Hello_World"), tmp_path)

        assert findings == [
            ValidationFinding("/id", "'Hello_World' does not match '^[a-z0-9-]{1,200}$'", Severity.ERROR)
        ]
