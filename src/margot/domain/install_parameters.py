"""Pure rules for `margot install` parameters on quadlet profiles.

A parameter's ``pointer`` names an environment variable of the systemd unit of the component it
targets. This module selects the applicable parameters, resolves their values (``--set`` over the
descriptor default), renders the drop-in text and encodes each ``Environment=`` line so that
systemd stores the value unchanged (observed byte-for-byte on Podman 5.8.2). No I/O, no console, no rich imports.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
import re
from typing import Any

DROPIN_NAME = "50-margot-parameters.conf"
DROPIN_HEADER = (
    "# Managed by margot - regenerated on every install.",
    "# Add your own overrides in a differently named file (e.g. 90-local.conf).",
)
SOURCE_DESCRIPTOR = "descriptor"
SOURCE_SET = "--set"
# Set by margot on every unit to the directory the files are installed in. A descriptor
# parameter may not use it as a pointer, and --set cannot reach it.
QUADLET_DIR_VARIABLE = "QUADLET_DIR"
RESERVED_VARIABLES = frozenset({QUADLET_DIR_VARIABLE})

_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESCAPES = {"\\": "\\\\", '"': '\\"', "%": "%%"}
_FORBIDDEN_IN_VALUE = ("\n", "\r", "\x00")


@dataclass(frozen=True)
class Binding:
    """One parameter value bound to one environment variable of one component.

    Attributes:
        parameter: The parameter name in the descriptor.
        component: The component whose units receive the variable.
        variable: The target pointer, used as the environment variable name.
        value: The string value (already rendered).
        source: ``descriptor`` or ``--set``.
    """

    parameter: str
    component: str
    variable: str
    value: str
    source: str


@dataclass(frozen=True)
class ParameterResolution:
    """Applied bindings, and the applicable parameters that have no value (not applied)."""

    bindings: tuple[Binding, ...]
    unapplied: tuple[str, ...]


def parse_set_options(values: Sequence[str]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Parse ``NAME=VALUE`` arguments. The value is everything after the first ``=``.

    Returns:
        The overrides (last value wins) and the names given more than once, in first-seen order.

    Raises:
        ValueError: An argument without ``=`` or without a name.
    """
    overrides: dict[str, str] = {}
    repeated: list[str] = []
    for raw in values:
        name, separator, value = raw.partition("=")
        if not separator or not name:
            raise ValueError(f"--set expects NAME=VALUE, got '{raw}'.")
        if name in overrides:
            repeated.append(name)
        overrides[name] = value
    return overrides, tuple(dict.fromkeys(repeated))


def resolve_parameters(
    doc: Mapping[str, Any],
    component_names: Iterable[str],
    overrides: Mapping[str, str],
) -> ParameterResolution:
    """Select the parameters that apply to the profile's components and resolve their values.

    A parameter applies when one of its ``targets[].components`` names a component of the selected
    profile. Targets of other components are ignored. ``--set`` wins over the descriptor ``value``.

    Raises:
        ValueError: An unknown ``--set`` name, a pointer that is not an environment variable name, a pointer
            that is reserved (``QUADLET_DIR``), two parameters that set one variable on one component, an array
            value that would be applied, or a value with a newline, carriage return or NUL. Each message names
            the parameter.
    """
    names = set(component_names)
    declared = doc.get("parameters") if isinstance(doc.get("parameters"), dict) else {}
    targets = _applicable_targets(declared, names)

    _check_pointers(targets)
    _check_reserved(targets)
    _check_overrides(overrides, targets)
    _check_conflicts(targets)

    bindings: list[Binding] = []
    unapplied: list[str] = []
    for parameter in sorted(targets):
        if parameter in overrides:
            value, source = overrides[parameter], SOURCE_SET
        else:
            raw = declared[parameter].get("value")
            if raw is None:
                unapplied.append(parameter)
                continue
            if isinstance(raw, list | dict):
                raise ValueError(
                    f"Parameter '{parameter}' has an array value. Quadlet parameters take one value; "
                    "array data types are not supported yet."
                )
            try:
                value = render_value(raw)
            except ValueError as error:
                raise ValueError(f"Parameter '{parameter}' {error}.") from error
            source = SOURCE_DESCRIPTOR
        for component, variable in dict.fromkeys(targets[parameter]):
            _check_value(parameter, component, value)
            bindings.append(Binding(parameter=parameter, component=component, variable=variable, value=value, source=source))
    bindings.sort(key=lambda binding: (binding.component, binding.variable))
    return ParameterResolution(bindings=tuple(bindings), unapplied=tuple(unapplied))


def render_value(value: object) -> str:
    """Render a descriptor scalar as the string that goes into the unit environment.

    Strings are used as they are; booleans are ``true``/``false``; integers and doubles are decimal.

    Raises:
        ValueError: A non-finite double, or a type that is not a scalar.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("is not a finite number and has no decimal form")
        return format(Decimal(repr(value)), "f")
    if isinstance(value, str):
        return value
    raise ValueError(f"has a value of type {type(value).__name__}, which is not a scalar")


def encode_environment(variable: str, value: str) -> str:
    """Return the ``Environment="NAME=value"`` line that systemd stores byte-for-byte (observed on Podman 5.8.2).

    The value is always double-quoted. Backslash and double quote are escaped with a backslash,
    and ``%`` is doubled because it is a unit-file specifier. ``$`` needs no escaping.

    Raises:
        ValueError: An invalid variable name, or a value with a newline, carriage return or NUL.
    """
    if not _VARIABLE_NAME.fullmatch(variable):
        raise ValueError(f"'{variable}' is not a valid environment variable name ([A-Za-z_][A-Za-z0-9_]*).")
    if any(character in value for character in _FORBIDDEN_IN_VALUE):
        raise ValueError(f"The value of '{variable}' contains a newline, carriage return or NUL, which are not supported.")
    escaped = "".join(_ESCAPES.get(character, character) for character in value)
    return f'Environment="{variable}={escaped}"'


def render_dropin(variables: Mapping[str, str]) -> str:
    """Return the text of ``50-margot-parameters.conf``: header, ``[Service]``, one line per variable, sorted."""
    lines = [*DROPIN_HEADER, "[Service]", *(encode_environment(name, variables[name]) for name in sorted(variables))]
    return "\n".join(lines) + "\n"


def dropin_relpath(unit_relpath: str) -> str:
    """Return the drop-in path beside a unit file: ``<unit file>.d/50-margot-parameters.conf``."""
    return f"{unit_relpath}.d/{DROPIN_NAME}"


def variables_by_unit(
    bindings: Iterable[Binding],
    units_by_component: Mapping[str, Sequence[str]],
    application_dir: str,
) -> dict[str, dict[str, str]]:
    """Map each unit file to the variables it receives.

    Every unit gets ``QUADLET_DIR`` set to the application directory, even when no parameter applies.
    A unit also receives every variable of every component that ships it. Two components that ship one
    unit may not set one variable to different values.

    Raises:
        ValueError: A unit would receive two values for one variable.
    """
    result: dict[str, dict[str, str]] = {}
    for units in units_by_component.values():
        for unit in units:
            result.setdefault(unit, {})[QUADLET_DIR_VARIABLE] = application_dir
    for binding in bindings:
        for unit in units_by_component.get(binding.component, ()):
            variables = result.setdefault(unit, {})
            known = variables.get(binding.variable)
            if known is not None and known != binding.value:
                raise ValueError(
                    f"Unit '{unit}' would get two values for {binding.variable} from the components that ship it. "
                    "Give the parameters different pointers."
                )
            variables[binding.variable] = binding.value
    return result


def _applicable_targets(declared: Mapping[str, Any], names: set[str]) -> dict[str, list[tuple[str, Any]]]:
    """Map each applicable parameter to its (component, pointer) pairs; other components are ignored."""
    targets: dict[str, list[tuple[str, Any]]] = {}
    for parameter, spec in declared.items():
        if not isinstance(spec, dict):
            continue
        for target in spec.get("targets") or []:
            if not isinstance(target, dict):
                continue
            for component in target.get("components") or []:
                if component in names:
                    targets.setdefault(str(parameter), []).append((component, target.get("pointer")))
    return targets


def _check_pointers(targets: Mapping[str, list[tuple[str, Any]]]) -> None:
    for parameter in sorted(targets):
        for component, pointer in targets[parameter]:
            if not (isinstance(pointer, str) and _VARIABLE_NAME.fullmatch(pointer)):
                raise ValueError(
                    f"Parameter '{parameter}' has pointer {pointer!r} for component '{component}'. "
                    "A quadlet pointer is an environment variable name ([A-Za-z_][A-Za-z0-9_]*)."
                )


def _check_reserved(targets: Mapping[str, list[tuple[str, Any]]]) -> None:
    for parameter in sorted(targets):
        for component, pointer in targets[parameter]:
            if pointer in RESERVED_VARIABLES:
                raise ValueError(
                    f"Parameter '{parameter}' uses pointer {pointer} on component '{component}', which is reserved by "
                    "margot (it holds the application directory). Give the parameter another pointer."
                )


def _check_overrides(overrides: Mapping[str, str], targets: Mapping[str, list[tuple[str, Any]]]) -> None:
    unknown = sorted(name for name in overrides if name not in targets)
    if not unknown:
        return
    applicable = ", ".join(sorted(targets)) or "none"
    raise ValueError(
        f"--set {unknown[0]}: not a parameter of this profile's components. Parameters that apply to this profile: {applicable}."
    )


def _check_conflicts(targets: Mapping[str, list[tuple[str, Any]]]) -> None:
    owner: dict[tuple[str, str], str] = {}
    for parameter in sorted(targets):
        for component, pointer in targets[parameter]:
            key = (component, pointer)
            if key in owner and owner[key] != parameter:
                raise ValueError(
                    f"Parameters '{owner[key]}' and '{parameter}' both set {pointer} on component '{component}'. "
                    "Give one of them another pointer."
                )
            owner[key] = parameter


def _check_value(parameter: str, component: str, value: str) -> None:
    if any(character in value for character in _FORBIDDEN_IN_VALUE):
        raise ValueError(
            f"Parameter '{parameter}' value for component '{component}' contains a newline, carriage return or NUL, "
            "which are not supported."
        )
