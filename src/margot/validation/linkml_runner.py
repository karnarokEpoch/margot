"""LinkML validation adapter — the only module in margot allowed to import linkml.

Validation logic itself belongs to ``linkml.validator``; this module's job is to run it
with margot's plugin set and translate LinkML report objects into margot's own
:class:`~margot.domain.validation.ValidationFinding`, so no caller ever handles a linkml
type.
"""

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
    return ValidationFinding(field_path, message, _SEVERITY_MAP.get(result.severity, Severity.ERROR))


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
