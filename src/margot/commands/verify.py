"""Verify command: validate the Margo application description against the spec schema."""

from collections.abc import Iterable

from rich.markup import escape
from typer import Option

from margot import console
from margot.domain.validation import Severity, ValidationFinding, VerifyResult
from margot.schemas import SCHEMA_A_SHORT_COMMIT
from margot.services import verify as verify_service
from margot.validation.error_formatter import format_findings, summarize

SCHEMA_A_LABEL = "Schema A (Margo spec)"
SCHEMA_B_LABEL = "Schema B (recommended)"

# Schema B is a lint pass: its findings are reported, but neither the verdict nor the exit
# code depends on them. Said on the summary line so a reader is not left wondering why a run
# with Schema B errors still passed.
ADVISORY_NOTE = "advisory, does not affect the exit code"


def verify_cmd(
    project_dir: str = Option(".", "--project-dir", help="Directory containing margo.yaml."),
    manifest: str | None = Option(None, "--manifest", help="Path to app.yaml or app.yaml.jinja."),
    schema: str | None = Option(None, "--schema", help="Override the vendored Margo spec schema."),
    recommended_schema: str | None = Option(None, "--recommended-schema", help="Override the bundled margot recommended schema."),
    recommend: bool = Option(False, "--recommend", help="Also lint against the margot recommended schema."),
) -> None:
    """Validate the Margo application description against the Margo spec schema."""
    try:
        result = verify_service.verify(
            project_dir=project_dir,
            manifest_path=manifest,
            schema_path=schema,
            recommended_schema_path=recommended_schema,
            recommend=recommend,
        )
    except ValueError as e:
        console.fatal(str(e))
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Verify failed: {e}")

    _render(result, recommend=recommend)


def _render(result: VerifyResult, recommend: bool) -> None:
    """Print the draft-spec line, the findings of each schema that ran, and the verdict."""
    console.success(f"Validated against Margo spec (draft, commit {SCHEMA_A_SHORT_COMMIT})")
    if recommend:
        _render_both_schemas(result)
    else:
        _render_schema_a_only(result)


def _render_schema_a_only(result: VerifyResult) -> None:
    """Print Schema A's findings unsectioned — with only one schema there is nothing to disambiguate."""
    findings = result.schema_a_results
    summary = summarize(findings)
    _emit(finding for finding in findings if finding.severity is not Severity.ERROR)

    if result.passed:
        console.success(f"{SCHEMA_A_LABEL}: PASS — {summary}")
        return

    errors = [finding for finding in findings if finding.severity is Severity.ERROR]
    error_lines = "\n".join(escape(line) for line in format_findings(errors))
    console.fatal(f"{error_lines}\n{SCHEMA_A_LABEL}: FAIL — {summary}")


def _render_both_schemas(result: VerifyResult) -> None:
    """Print one labeled section per schema, then the verdict.

    Both sections are always shown, including when a schema found nothing: "Schema B ran and
    is clean" and "Schema B never ran" must not look the same. Schema A errors go out as
    warning lines here rather than through `console.fatal`, because `fatal` exits and the
    Schema B section still has to be printed; the verdict below does the exiting.
    """
    console.success(_section(SCHEMA_A_LABEL))
    _emit(result.schema_a_results)
    verdict = "PASS" if result.passed else "FAIL"
    console.success(f"{SCHEMA_A_LABEL}: {verdict} — {summarize(result.schema_a_results)}")

    console.success(_section(SCHEMA_B_LABEL))
    _emit(result.schema_b_results)
    console.success(f"{SCHEMA_B_LABEL}: {summarize(result.schema_b_results)} — {ADVISORY_NOTE}")

    if result.passed:
        console.success(f"verify: {verdict}")
        return
    console.fatal(f"verify: {verdict}")


def _emit(findings: Iterable[ValidationFinding]) -> None:
    """Print findings as plain warning lines, with rich markup in messages escaped."""
    for line in format_findings(list(findings)):
        console.warning(escape(line))


def _section(label: str) -> str:
    """Return a plain section separator for one schema's findings."""
    return f"── {label} ──"
