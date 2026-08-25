"""Unit tests for domain/validation.py dataclasses — pure data, no mocks, no I/O."""

from dataclasses import FrozenInstanceError

from pytest import raises

from margot.domain.validation import Severity, ValidationFinding, VerifyResult, has_errors


class TestSeverity:
    """Tests for the Severity enum."""

    def test_severity_members(self) -> None:
        """Should expose exactly ERROR, WARNING and INFO."""
        assert [member.name for member in Severity] == ["ERROR", "WARNING", "INFO"]

    def test_severity_values_are_uppercase_labels(self) -> None:
        """Should carry uppercase string values usable as output labels."""
        assert Severity.ERROR.value == "ERROR"
        assert Severity.WARNING.value == "WARNING"
        assert Severity.INFO.value == "INFO"


class TestValidationFinding:
    """Tests for the ValidationFinding dataclass."""

    def test_construction_keeps_all_fields(self) -> None:
        """Should store field_path, message and severity as given."""
        finding = ValidationFinding("/metadata/version", "'version' is a required property", Severity.ERROR)

        assert finding.field_path == "/metadata/version"
        assert finding.message == "'version' is a required property"
        assert finding.severity is Severity.ERROR

    def test_finding_is_frozen(self) -> None:
        """Should refuse mutation after construction."""
        finding = ValidationFinding("/", "boom", Severity.WARNING)

        with raises(FrozenInstanceError):
            finding.message = "changed"

    def test_findings_compare_by_value(self) -> None:
        """Should treat two identical findings as equal."""
        first = ValidationFinding("/id", "bad id", Severity.ERROR)
        second = ValidationFinding("/id", "bad id", Severity.ERROR)

        assert first == second


class TestVerifyResult:
    """Tests for the VerifyResult dataclass."""

    def test_defaults_are_empty_and_passing(self) -> None:
        """Should default to no findings, empty version and passed=True."""
        result = VerifyResult()

        assert result.schema_a_results == []
        assert result.schema_b_results == []
        assert result.schema_a_version == ""
        assert result.passed is True

    def test_construction_with_findings(self) -> None:
        """Should keep Schema A findings, version string and passed flag."""
        finding = ValidationFinding("/metadata", "'version' is a required property", Severity.ERROR)
        result = VerifyResult(
            schema_a_results=[finding],
            schema_b_results=[],
            schema_a_version="45f4359d129c1f04532d17b358d6f50eaa3ca62f",
            passed=False,
        )

        assert result.schema_a_results == [finding]
        assert result.schema_b_results == []
        assert result.schema_a_version == "45f4359d129c1f04532d17b358d6f50eaa3ca62f"
        assert result.passed is False

    def test_result_is_frozen(self) -> None:
        """Should refuse mutation after construction."""
        result = VerifyResult(schema_a_version="abc", passed=True)

        with raises(FrozenInstanceError):
            result.passed = False

    def test_default_lists_are_independent_per_instance(self) -> None:
        """Should not share the default list between instances."""
        first = VerifyResult()
        second = VerifyResult()

        assert first.schema_a_results is not second.schema_a_results


class TestHasErrors:
    """Tests for the has_errors passed-semantics helper."""

    def test_no_findings_has_no_errors(self) -> None:
        """Should report no errors for an empty finding list."""
        assert has_errors([]) is False

    def test_warnings_and_infos_are_not_errors(self) -> None:
        """Should ignore WARNING and INFO severities."""
        findings = [
            ValidationFinding("/metadata/description", "recommended", Severity.WARNING),
            ValidationFinding("/", "informational", Severity.INFO),
        ]

        assert has_errors(findings) is False

    def test_single_error_is_detected(self) -> None:
        """Should report an error when at least one ERROR finding is present."""
        findings = [
            ValidationFinding("/metadata/description", "recommended", Severity.WARNING),
            ValidationFinding("/metadata", "'version' is a required property", Severity.ERROR),
        ]

        assert has_errors(findings) is True
