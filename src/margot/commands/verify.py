"""Verify command: validate the Margo application description against the spec schema."""

from collections.abc import Iterable, Sequence

from rich.markup import escape
from typer import Option

from margot import console
from margot.domain.validation import Severity, ValidationFinding, VerifyResult, has_errors
from margot.schemas import SCHEMA_A_SHORT_COMMIT
from margot.services import verify as verify_service
from margot.validation.error_formatter import format_findings, summarize

SCHEMA_A_LABEL = "Schema A (Margo spec)"
SCHEMA_B_LABEL = "Schema B (recommended)"

# Schema B is a lint pass unless --strict is passed: its findings are reported, but neither
# the verdict nor the exit code depends on them. Said on the summary line so a reader is not
# left wondering why a run with Schema B errors still passed.
ADVISORY_NOTE = "advisory, does not affect the exit code"

MUTUALLY_EXCLUSIVE = "--recommend and --only-recommend are mutually exclusive — pass one or the other."
STRICT_NO_OP = "--strict has no effect without --recommend or --only-recommend. Schema B is not run."


def verify_cmd(  # noqa: PLR0913
    project_dir: str = Option(".", "--project-dir", help="Directory containing margo.yaml."),
    manifest: str | None = Option(None, "--manifest", help="Path to app.yaml or app.yaml.jinja."),
    schema: str | None = Option(None, "--schema", help="Override the vendored Margo spec schema."),
    recommended_schema: str | None = Option(None, "--recommended-schema", help="Override the bundled margot recommended schema."),
    recommend: bool = Option(False, "--recommend", help="Also lint against the margot recommended schema."),
    strict: bool = Option(False, "--strict", help="Make any recommended-schema finding fail the run."),
    only_recommend: bool = Option(
        False, "--only-recommend", help="Lint against the recommended schema only, skipping the Margo spec schema."
    ),
) -> None:
    """Validate the Margo application description against the Margo spec schema."""
    if recommend and only_recommend:
        console.fatal(MUTUALLY_EXCLUSIVE)
    if strict and not (recommend or only_recommend):
        console.warning(STRICT_NO_OP)

    try:
        result = verify_service.verify(
            project_dir=project_dir,
            manifest_path=manifest,
            schema_path=schema,
            recommended_schema_path=recommended_schema,
            recommend=recommend,
            strict=strict,
            only_recommend=only_recommend,
        )
    except ValueError as e:
        console.fatal(str(e))
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Verify failed: {e}")

    _render(result, recommend=recommend, strict=strict, only_recommend=only_recommend)


def _render(result: VerifyResult, recommend: bool, strict: bool, only_recommend: bool) -> None:
    """Print the findings of each schema that ran, and the verdict."""
    if only_recommend:
        _render_schema_b_only(result, strict)
        return

    console.success(f"Validated against Margo spec (draft, commit {SCHEMA_A_SHORT_COMMIT})")
    if recommend and (result.schema_a_results or result.schema_b_results):
        _render_both_schemas(result, strict)
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


def _render_schema_b_only(result: VerifyResult, strict: bool) -> None:
    """Print Schema B's findings unsectioned, then the verdict.

    No draft-spec line and no Schema A section: Schema A never ran, and claiming a spec
    check that did not happen would be a lie.
    """
    _emit(result.schema_b_results)
    console.success(_schema_b_summary(result.schema_b_results, strict))
    _verdict(result)


def _render_both_schemas(result: VerifyResult, strict: bool) -> None:
    """Print one labeled section per schema, then the verdict.

    Only reached when at least one schema found something: with both clean there is no finding
    to attribute, so the sections would be noise and `_render` prints the plain Schema A output
    instead. As soon as either schema reports anything, both sections are shown — a reader must
    never have to guess which schema a finding came from, nor whether the other one ran.

    Schema A errors go out as warning lines here rather than through `console.fatal`, because
    `fatal` exits and the Schema B section still has to be printed; the verdict below does the
    exiting. Schema A's own verdict is derived from its own findings — under `--strict` the run
    can fail on Schema B alone, which says nothing about Schema A.
    """
    console.success(_section(SCHEMA_A_LABEL))
    _emit(result.schema_a_results)
    schema_a_verdict = "FAIL" if has_errors(result.schema_a_results) else "PASS"
    console.success(f"{SCHEMA_A_LABEL}: {schema_a_verdict} — {summarize(result.schema_a_results)}")

    console.success(_section(SCHEMA_B_LABEL))
    _emit(result.schema_b_results)
    console.success(_schema_b_summary(result.schema_b_results, strict))

    _verdict(result)


def _schema_b_summary(findings: Sequence[ValidationFinding], strict: bool) -> str:
    """Return Schema B's summary line: a verdict under `--strict`, an advisory count otherwise."""
    summary = summarize(findings)
    if not strict:
        return f"{SCHEMA_B_LABEL}: {summary} — {ADVISORY_NOTE}"
    return f"{SCHEMA_B_LABEL}: {'FAIL' if findings else 'PASS'} — {summary}"


def _verdict(result: VerifyResult) -> None:
    """Print the final pass/fail line, exiting 1 on failure."""
    if result.passed:
        console.success("verify: PASS")
        return
    console.fatal("verify: FAIL")


def _emit(findings: Iterable[ValidationFinding]) -> None:
    """Print findings as plain warning lines, with rich markup in messages escaped."""
    for line in format_findings(list(findings)):
        console.warning(escape(line))


def _section(label: str) -> str:
    """Return a plain section separator for one schema's findings."""
    return f"── {label} ──"
