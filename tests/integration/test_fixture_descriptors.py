"""Tests reading `app.yaml` fixtures from disk instead of inline strings.

Companion to `test_recommended_schema.py`, which builds descriptors as Python strings.
These fixtures under `tests/fixtures/app-descriptions/` are standalone files — see the
README there for what each one demonstrates and its exact expected findings — usable
directly by `margot verify --manifest` or any future `margot describe` test, not just
from Python.
"""

from pathlib import Path

from margot.domain.validation import Severity, ValidationFinding
from margot.schemas import (
    SCHEMA_A_PATH,
    SCHEMA_A_TARGET_CLASS,
    SCHEMA_B_PATH,
    SCHEMA_B_TARGET_CLASS,
)
from margot.validation.linkml_runner import run_validation

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "app-descriptions"


def _fixture(name: str) -> str:
    """Return the path to a fixture file, failing loudly if it was renamed or removed."""
    path = FIXTURES_DIR / f"{name}.yaml"
    assert path.is_file(), f"missing fixture: {path}"
    return str(path)


def _errors(findings: list[ValidationFinding]) -> list[ValidationFinding]:
    return [f for f in findings if f.severity is Severity.ERROR]


def _warnings(findings: list[ValidationFinding]) -> list[ValidationFinding]:
    return [f for f in findings if f.severity is Severity.WARNING]


class TestMinimal:
    """The smallest spec-compliant descriptor: clean on Schema A, warnings-only on B."""

    def test_clean_on_schema_a(self) -> None:
        findings = run_validation(_fixture("minimal"), SCHEMA_A_PATH, SCHEMA_A_TARGET_CLASS)

        assert findings == []

    def test_warns_on_schema_b_recommended_slots_only(self) -> None:
        findings = run_validation(_fixture("minimal"), SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS)

        assert _errors(findings) == []
        assert len(_warnings(findings)) == 3


class TestComplex:
    """A full-featured, catalog-ready descriptor: clean on both schemas."""

    def test_clean_on_schema_a(self) -> None:
        findings = run_validation(_fixture("complex"), SCHEMA_A_PATH, SCHEMA_A_TARGET_CLASS)

        assert findings == []

    def test_clean_on_schema_b(self) -> None:
        findings = run_validation(_fixture("complex"), SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS)

        assert findings == []


class TestMissingRecommended:
    """Required fields present; recommended catalog fields thin or absent."""

    def test_clean_on_schema_a(self) -> None:
        findings = run_validation(_fixture("missing-recommended"), SCHEMA_A_PATH, SCHEMA_A_TARGET_CLASS)

        assert findings == []

    def test_warns_five_times_on_schema_b(self) -> None:
        findings = run_validation(_fixture("missing-recommended"), SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS)

        assert _errors(findings) == []
        assert len(_warnings(findings)) == 5
        assert {f.field_path for f in findings} == {
            "/metadata",
            "/metadata/catalog/application",
            "/metadata/catalog",
        }


class TestUnlinkedParameters:
    """Dangling parameter/setting/schema references — invisible to LinkML by design."""

    def test_clean_on_schema_a(self) -> None:
        findings = run_validation(_fixture("unlinked-parameters"), SCHEMA_A_PATH, SCHEMA_A_TARGET_CLASS)

        assert findings == []

    def test_only_recommended_slot_warnings_on_schema_b(self) -> None:
        findings = run_validation(_fixture("unlinked-parameters"), SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS)

        assert _errors(findings) == []
        assert len(_warnings(findings)) == 2


class TestMissingRequired:
    """Several spec-required fields absent — Schema A and Schema B disagree on cardinality."""

    def test_schema_a_reports_three_errors(self) -> None:
        findings = run_validation(_fixture("missing-required"), SCHEMA_A_PATH, SCHEMA_A_TARGET_CLASS)

        assert len(_errors(findings)) == 3
        assert _warnings(findings) == []

    def test_schema_b_reports_an_extra_cardinality_error(self) -> None:
        """Should report Schema A's 3 errors plus the empty-components cardinality error."""
        findings = run_validation(_fixture("missing-required"), SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS)
        errors = _errors(findings)

        assert len(errors) == 4
        assert len(_warnings(findings)) == 3
        assert any(f.field_path == "/deploymentProfiles/0/components" and "non-empty" in f.message for f in errors)
