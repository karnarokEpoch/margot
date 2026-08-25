"""Verify command: validate the Margo application description against the spec schema."""

from rich.markup import escape
from typer import Option

from margot import console
from margot.domain.validation import Severity, VerifyResult
from margot.schemas import SCHEMA_A_SHORT_COMMIT
from margot.services import verify as verify_service
from margot.validation.error_formatter import format_findings, summarize

SCHEMA_A_LABEL = "Schema A (Margo spec)"


def verify_cmd(
    project_dir: str = Option(".", "--project-dir", help="Directory containing margo.yaml."),
    manifest: str | None = Option(None, "--manifest", help="Path to app.yaml or app.yaml.jinja."),
    schema: str | None = Option(None, "--schema", help="Override the vendored Margo spec schema."),
) -> None:
    """Validate the Margo application description against the Margo spec schema."""
    try:
        result = verify_service.verify(project_dir=project_dir, manifest_path=manifest, schema_path=schema)
    except ValueError as e:
        console.fatal(str(e))
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Verify failed: {e}")

    _render(result)


def _render(result: VerifyResult) -> None:
    """Print the draft-spec line, the Schema A findings and the verdict."""
    console.success(f"Validated against Margo spec (draft, commit {SCHEMA_A_SHORT_COMMIT})")

    findings = result.schema_a_results
    summary = summarize(findings)
    non_errors = [finding for finding in findings if finding.severity is not Severity.ERROR]
    errors = [finding for finding in findings if finding.severity is Severity.ERROR]

    for line in format_findings(non_errors):
        console.warning(escape(line))

    if result.passed:
        console.success(f"{SCHEMA_A_LABEL}: PASS — {summary}")
        return

    error_lines = "\n".join(escape(line) for line in format_findings(errors))
    console.fatal(f"{error_lines}\n{SCHEMA_A_LABEL}: FAIL — {summary}")
