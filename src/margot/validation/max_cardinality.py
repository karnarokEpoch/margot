"""Maximum cardinality validation plugin.

linkml 1.11.1 ships ``JsonschemaValidationPlugin``, ``PydanticValidationPlugin``,
``InstantiatesValidationPlugin`` and ``RecommendedSlotsPlugin`` — but no maximum
cardinality plugin, so this module provides one. If linkml ever ships its own, replace
the body of this module with a re-export.

Scope: only *map-form* multivalued slots (``inlined_as_list: false``). For list-form
slots linkml's JSON Schema generator already emits ``maxItems``, so
``JsonschemaValidationPlugin`` reports the breach and checking it here again would
double-report every finding. It emits no ``maxProperties`` for map-form slots, which is
the gap this plugin closes.
"""

from collections.abc import Iterator
from typing import Any

from linkml.validator.plugins.validation_plugin import ValidationPlugin
from linkml.validator.report import Severity, ValidationResult
from linkml.validator.validation_context import ValidationContext

from margot import console


class MaximumCardinalityPlugin(ValidationPlugin):
    """Report map-form multivalued slots holding more entries than ``maximum_cardinality`` allows."""

    def process(self, instance: Any, context: ValidationContext) -> Iterator[ValidationResult]:  # noqa: ANN401
        """Yield an ERROR result per slot exceeding its declared maximum cardinality."""
        console.debug("Validate maximum cardinality constraints")
        yield from self._process_class(instance, context, context.target_class, [])

    def _process_class(
        self,
        instance: Any,  # noqa: ANN401
        context: ValidationContext,
        class_name: str,
        location: list[str],
    ) -> Iterator[ValidationResult]:
        """Walk one class instance, checking its slots and recursing into inlined ranges."""
        if not isinstance(instance, dict):
            return

        for slot in context.schema_view.class_induced_slots(class_name):
            value = instance.get(slot.name)
            if value is None:
                continue
            slot_location = [*location, slot.name]
            if slot.maximum_cardinality is not None and slot.multivalued and isinstance(value, dict):
                yield from self._check_cardinality(value, slot.name, slot.maximum_cardinality, class_name, slot_location)
            range_class = context.schema_view.get_class(slot.range)
            if range_class is not None:
                yield from self._recurse(value, context, range_class.name, slot, slot_location)

    def _check_cardinality(
        self,
        value: dict,
        slot_name: str,
        maximum: int,
        class_name: str,
        location: list[str],
    ) -> Iterator[ValidationResult]:
        """Yield a result when a map-form slot holds more entries than allowed."""
        if len(value) <= maximum:
            return
        yield ValidationResult(
            type="maximum cardinality",
            severity=Severity.ERROR,
            instance=value,
            instantiates=class_name,
            message=(
                f"Slot '{slot_name}' on class '{class_name}' allows at most {maximum} "
                f"value(s), got {len(value)} in /{'/'.join(location)}"
            ),
        )

    def _recurse(
        self,
        value: Any,  # noqa: ANN401
        context: ValidationContext,
        range_class_name: str,
        slot: Any,  # noqa: ANN401
        location: list[str],
    ) -> Iterator[ValidationResult]:
        """Recurse into inlined class-ranged slot values (list or map form)."""
        if not slot.multivalued:
            yield from self._process_class(value, context, range_class_name, location)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                yield from self._process_class(item, context, range_class_name, [*location, str(key)])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from self._process_class(item, context, range_class_name, [*location, str(index)])
