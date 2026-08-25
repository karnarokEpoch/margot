"""Format validation findings into plain text and row tuples.

Returns data only — no rich objects, no printing. ``commands/verify.py`` owns rendering.
"""

from collections.abc import Sequence

from margot.domain.validation import Severity, ValidationFinding


def format_finding(finding: ValidationFinding) -> str:
    """Format one finding as a single plain line: ``SEVERITY path: message``."""
    return f"{finding.severity.value} {finding.field_path}: {finding.message}"


def format_findings(findings: Sequence[ValidationFinding]) -> list[str]:
    """Format findings as plain lines, in report order."""
    return [format_finding(finding) for finding in findings]


def finding_rows(findings: Sequence[ValidationFinding]) -> list[tuple[str, str, str]]:
    """Return findings as ``(field_path, message, severity)`` tuples of plain strings."""
    return [(finding.field_path, finding.message, finding.severity.value) for finding in findings]


def summarize(findings: Sequence[ValidationFinding]) -> str:
    """Summarize findings by severity, e.g. ``"1 error, 2 warnings"`` or ``"no findings"``."""
    counts = [
        (sum(1 for finding in findings if finding.severity is Severity.ERROR), "error", "errors"),
        (sum(1 for finding in findings if finding.severity is Severity.WARNING), "warning", "warnings"),
        (sum(1 for finding in findings if finding.severity is Severity.INFO), "info", "infos"),
    ]
    parts = [f"{count} {singular if count == 1 else plural}" for count, singular, plural in counts if count]
    if not parts:
        return "no findings"
    return ", ".join(parts)
