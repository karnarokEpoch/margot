"""Validation result dataclasses: pure data, no I/O, no linkml, no console."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    """Severity of a single validation finding."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True)
class ValidationFinding:
    """One finding reported by a schema validation pass."""

    field_path: str
    message: str
    severity: Severity


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of a `margot verify` run.

    `schema_b_results` stays empty until the recommended schema (Schema B) is wired;
    the field exists now because the result shape is shared by every verify mode.
    """

    schema_a_results: list[ValidationFinding] = field(default_factory=list)
    schema_b_results: list[ValidationFinding] = field(default_factory=list)
    schema_a_version: str = ""
    passed: bool = True


def has_errors(findings: Sequence[ValidationFinding]) -> bool:
    """Return True if any finding has ERROR severity."""
    return any(finding.severity is Severity.ERROR for finding in findings)
