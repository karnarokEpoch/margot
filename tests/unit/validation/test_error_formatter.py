"""Unit tests for validation/error_formatter.py — plain data in, plain data out."""

from margot.domain.validation import Severity, ValidationFinding
from margot.validation.error_formatter import finding_rows, format_finding, format_findings, summarize

ERROR_FINDING = ValidationFinding("/metadata", "'version' is a required property", Severity.ERROR)
WARNING_FINDING = ValidationFinding("/", "Slot 'description' is recommended on class 'Metadata'", Severity.WARNING)
INFO_FINDING = ValidationFinding("/parameters/greeting", "informational note", Severity.INFO)


class TestFormatFinding:
    """Tests for format_finding."""

    def test_error_line(self) -> None:
        """Should render severity, field path and message on one line."""
        assert format_finding(ERROR_FINDING) == "ERROR /metadata: 'version' is a required property"

    def test_warning_line(self) -> None:
        """Should label warnings with the WARNING severity."""
        assert format_finding(WARNING_FINDING) == "WARNING /: Slot 'description' is recommended on class 'Metadata'"

    def test_info_line(self) -> None:
        """Should label informational findings with the INFO severity."""
        assert format_finding(INFO_FINDING) == "INFO /parameters/greeting: informational note"

    def test_returns_plain_string(self) -> None:
        """Should return a plain str, never a rich renderable."""
        assert type(format_finding(ERROR_FINDING)) is str


class TestFormatFindings:
    """Tests for format_findings."""

    def test_empty_list(self) -> None:
        """Should return no lines for no findings."""
        assert format_findings([]) == []

    def test_preserves_report_order(self) -> None:
        """Should keep the order the findings were reported in."""
        assert format_findings([WARNING_FINDING, ERROR_FINDING]) == [
            "WARNING /: Slot 'description' is recommended on class 'Metadata'",
            "ERROR /metadata: 'version' is a required property",
        ]


class TestFindingRows:
    """Tests for finding_rows."""

    def test_row_tuples(self) -> None:
        """Should return (field_path, message, severity) tuples of plain strings."""
        assert finding_rows([ERROR_FINDING, WARNING_FINDING]) == [
            ("/metadata", "'version' is a required property", "ERROR"),
            ("/", "Slot 'description' is recommended on class 'Metadata'", "WARNING"),
        ]

    def test_empty_list(self) -> None:
        """Should return no rows for no findings."""
        assert finding_rows([]) == []


class TestSummarize:
    """Tests for summarize."""

    def test_no_findings(self) -> None:
        """Should state that nothing was found."""
        assert summarize([]) == "no findings"

    def test_single_error(self) -> None:
        """Should use the singular noun for a single finding."""
        assert summarize([ERROR_FINDING]) == "1 error"

    def test_mixed_severities(self) -> None:
        """Should count each severity and list them in ERROR, WARNING, INFO order."""
        findings = [WARNING_FINDING, ERROR_FINDING, WARNING_FINDING, INFO_FINDING]

        assert summarize(findings) == "1 error, 2 warnings, 1 info"

    def test_omits_absent_severities(self) -> None:
        """Should not mention severities with a zero count."""
        assert summarize([WARNING_FINDING, WARNING_FINDING]) == "2 warnings"
