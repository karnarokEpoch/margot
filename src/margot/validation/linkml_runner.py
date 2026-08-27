"""LinkML validation adapter — the only module in margot allowed to import linkml.

Validation logic itself belongs to ``linkml.validator``; this module's job is to run it
with margot's plugin set and translate LinkML report objects into margot's own
:class:`~margot.domain.validation.ValidationFinding`, so no caller ever handles a linkml
type.
"""

from collections.abc import Iterator
from pathlib import Path
import re
from typing import Any

from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin, RecommendedSlotsPlugin
from linkml.validator.report import Severity as LinkmlSeverity
from linkml.validator.report import ValidationResult

from margot import console
from margot.domain.validation import Severity, ValidationFinding
from margot.infra.filesystem import load_yaml
from margot.validation.max_cardinality import MaximumCardinalityPlugin

# The Margo spec allows vendor-specific content under `x-placeholder-extensions` on
# ApplicationDescription, DeploymentProfile and Component. LinkML's JSON Schema
# generator renames that slot to `x_placeholder_extensions` and types it as an array,
# so a spec-valid descriptor carrying the real, hyphenated mapping is reported as
# "Additional properties are not allowed" (top level) or "is not valid under any of the
# given schemas" (nested) — with `closed=True` *and* with `closed=False`, because nested
# class definitions stay closed either way. Dropping JsonschemaValidationPlugin would
# also drop required-field, pattern and enum checking, i.e. all of Schema A's value, so
# instead the extension slot is removed from the instance before validation. Extension
# content is vendor-defined and outside the spec's own vocabulary: there is nothing for
# LinkML to check inside it.
EXTENSION_SLOT = "x-placeholder-extensions"

# Trailing " in /some/path" location suffix that linkml plugins append to messages.
_LOCATION_SUFFIX = re.compile(r"^(?P<message>.*) in (?P<path>/\S*)$", re.DOTALL)

# jsonschema builds its oneOf/anyOf message as f"{instance!r} is not valid under any of the
# given schemas", i.e. it inlines a repr of the whole failing sub-object — for a polymorphic
# slot like deploymentProfiles[].components[].properties that is the entire profile, which
# makes the one-line `margot verify` output unreadable. The same error carries `.context`:
# one sub-error per candidate schema branch that failed, each with its own specific message
# and path. Those sub-errors are summarized instead of the flat message linkml passes on.
_ALTERNATIVE_VALIDATORS = ("oneOf", "anyOf")

# A oneOf/anyOf failure fans out one sub-error per branch per offending field, so the raw
# list is both long and repetitive. Three distinct reasons is enough to act on; the rest is
# reported as a count. Individual reasons are capped too: a nested `type` sub-error still
# reprs its own instance, and that instance can itself be a large mapping.
_MAX_REASONS = 3
_MAX_REASON_LENGTH = 120

# Header for the case where the branches disagree about *different* fields, so no single
# field can be blamed and each reason has to carry its own path.
_NO_MATCH_HEADER = "no matching schema — possible causes"

_SEVERITY_MAP = {
    LinkmlSeverity.FATAL: Severity.ERROR,
    LinkmlSeverity.ERROR: Severity.ERROR,
    LinkmlSeverity.WARN: Severity.WARNING,
    LinkmlSeverity.INFO: Severity.INFO,
}


def run_validation(data_path: str, schema_path: str, target_class: str | None = None) -> list[ValidationFinding]:
    """Validate a YAML document against a LinkML schema.

    Args:
        data_path: Path to the YAML instance document.
        schema_path: Path to the LinkML schema file.
        target_class: Root class to validate against. When omitted, linkml infers it,
            which fails on schemas declaring more than one candidate root.

    Returns:
        Findings in report order. A missing/unparseable document, an unusable schema or
        an unknown target class each yield a single ERROR finding — validation problems
        are reported, never raised.
    """
    console.debug(f"Validate {data_path} against schema {schema_path}")
    try:
        instance = load_yaml(data_path)
    except ValueError as e:
        return [ValidationFinding("/", str(e), Severity.ERROR)]

    if not isinstance(instance, dict):
        return [ValidationFinding("/", "Expected a YAML mapping at the document root.", Severity.ERROR)]

    try:
        results = _validate(strip_extension_slots(instance), schema_path, target_class)
    except (ValueError, RuntimeError) as e:
        return [ValidationFinding("/", f"Schema could not be applied: {e}", Severity.ERROR)]

    return [_to_finding(result) for result in results]


def strip_extension_slots(value: Any) -> Any:  # noqa: ANN401
    """Return a copy of value with every `x-placeholder-extensions` mapping removed.

    See the EXTENSION_SLOT comment above for why this is needed.
    """
    if isinstance(value, dict):
        return {key: strip_extension_slots(item) for key, item in value.items() if key != EXTENSION_SLOT}
    if isinstance(value, list):
        return [strip_extension_slots(item) for item in value]
    return value


def _validate(instance: dict, schema_path: str, target_class: str | None) -> list[ValidationResult]:
    """Run linkml's validator with margot's plugin set."""
    console.debug(f"Load schema: {schema_path}")
    validator = Validator(
        Path(schema_path),
        validation_plugins=[
            JsonschemaValidationPlugin(closed=True),
            RecommendedSlotsPlugin(),
            MaximumCardinalityPlugin(),
        ],
    )
    console.debug(f"Run linkml validation (target class: {target_class or 'inferred'})")
    return list(validator.validate(instance, target_class).results)


def _to_finding(result: ValidationResult) -> ValidationFinding:
    """Map one linkml ValidationResult onto a margot ValidationFinding."""
    message, field_path = _split_location(result.message)
    if not field_path:
        field_path = _source_path(result)
    summary, shared_path = _alternatives_summary(result.source)
    return ValidationFinding(
        _join_path(field_path, shared_path) if summary else field_path,
        summary or message,
        _SEVERITY_MAP.get(result.severity, Severity.ERROR),
    )


def _alternatives_summary(source: Any) -> tuple[str, str]:  # noqa: ANN401
    """Summarize a jsonschema oneOf/anyOf failure from its per-branch sub-errors.

    Returns ``(message, shared_path)``. When every branch failed on the same field —
    the common case for a discriminated polymorphic slot, where each candidate schema
    rejects the same `type` value for its own reason — `shared_path` is that field's path
    relative to the failure and the message lists the distinct reasons only; the caller
    appends the path to the finding's own path so it is named once, not once per reason.
    Otherwise `shared_path` is empty and each reason carries its own path.

    Returns ``("", "")`` for anything that is not such a failure — every other message
    passes through untouched. Duck-typed on purpose: jsonschema is reached only through
    linkml, and the attributes used here (`validator`, `context`, `absolute_path`,
    `message`) are the whole contract this needs.
    """
    if getattr(source, "validator", None) not in _ALTERNATIVE_VALIDATORS:
        return "", ""
    if not getattr(source, "context", None):
        return "", ""
    shared_path = _shared_reason_path(source)
    reasons = _render_reasons(_branch_reasons(source, bare=shared_path is not None))
    if shared_path is None:
        return f"{_NO_MATCH_HEADER}: {reasons}", ""
    return reasons, shared_path


def _render_reasons(reasons: list[str]) -> str:
    """Join reasons into one line, capped at `_MAX_REASONS` with a count of the remainder."""
    omitted = len(reasons) - _MAX_REASONS
    tail = f"; +{omitted} more" if omitted > 0 else ""
    return f"{'; '.join(reasons[:_MAX_REASONS])}{tail}"


def _shared_reason_path(source: Any) -> str | None:  # noqa: ANN401
    """Return the single relative path all branch reasons are about, or None if they differ."""
    root_depth = len(list(getattr(source, "absolute_path", None) or ()))
    paths = {_relative_path(error, root_depth) for error in _leaf_errors(source)}
    if len(paths) != 1:
        return None
    return paths.pop()


def _branch_reasons(source: Any, bare: bool = False) -> list[str]:  # noqa: ANN401
    """Return the distinct, most specific reasons behind a oneOf/anyOf failure, in report order.

    With `bare`, reasons are rendered without their path — callers use this once they know
    every reason shares the same path and have promoted it into the finding's own path.
    """
    root_depth = len(list(getattr(source, "absolute_path", None) or ()))
    reasons: list[str] = []
    for error in _leaf_errors(source):
        reason = _format_reason(error, root_depth, bare=bare)
        if reason not in reasons:
            reasons.append(reason)
    return reasons


def _leaf_errors(error: Any) -> Iterator[Any]:  # noqa: ANN401
    """Yield the most specific sub-errors, descending through nested oneOf/anyOf nodes.

    Branches are themselves polymorphic, so a sub-error can be another oneOf/anyOf carrying
    the same instance-repr message. Only the leaves say something specific.
    """
    context = getattr(error, "context", None)
    if getattr(error, "validator", None) in _ALTERNATIVE_VALIDATORS and context:
        for sub_error in context:
            yield from _leaf_errors(sub_error)
    else:
        yield error


def _format_reason(error: Any, root_depth: int, bare: bool = False) -> str:  # noqa: ANN401
    """Render one sub-error as ``(at path: message)``, or as its bare message when `bare`."""
    path = _relative_path(error, root_depth)
    message = str(getattr(error, "message", ""))
    if len(message) > _MAX_REASON_LENGTH:
        message = f"{message[:_MAX_REASON_LENGTH].rstrip()}..."
    if bare:
        return message
    return f"(at {path}: {message})" if path else f"({message})"


def _relative_path(error: Any, root_depth: int) -> str:  # noqa: ANN401
    """Return a sub-error's instance path relative to the failure it belongs to."""
    parts = list(getattr(error, "absolute_path", None) or ())[root_depth:]
    return "/".join(str(part) for part in parts)


def _join_path(field_path: str, relative_path: str) -> str:
    """Append a relative instance path to a finding's field path."""
    if not relative_path:
        return field_path
    return f"{field_path.rstrip('/')}/{relative_path}"


def _split_location(message: str) -> tuple[str, str]:
    """Split a linkml message into its text and its trailing instance location."""
    match = _LOCATION_SUFFIX.match(message)
    if match is None:
        return message, ""
    return match.group("message"), match.group("path")


def _source_path(result: ValidationResult) -> str:
    """Derive an instance path from the underlying jsonschema error, if any."""
    absolute_path = getattr(result.source, "absolute_path", None)
    if absolute_path is None:
        return "/"
    return "/" + "/".join(str(part) for part in absolute_path)
