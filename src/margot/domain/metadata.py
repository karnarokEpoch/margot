"""Margo.yaml dataclasses and YAML parser: pure functions, no I/O."""

from dataclasses import dataclass
from pathlib import Path

from yaml import YAMLError, safe_load


@dataclass(frozen=True)
class VariantConfig:
    """Configuration for a single variant."""

    name: str
    version: str  # OCI tag as stored (may contain '_')


@dataclass(frozen=True)
class ComponentConfig:
    """Configuration for a component (margo, compose, or quadlet)."""

    directory: str
    version: str | None  # None when variants are declared
    repository: str | None  # optional override
    variants: tuple[VariantConfig, ...]  # empty tuple = no variants


@dataclass(frozen=True)
class MargoYaml:
    """Parsed margo.yaml file structure."""

    api_version: str  # apiVersion field
    name: str
    description: str
    app_version: str | None  # appVersion field (optional, not validated)
    annotations: dict[str, str]  # optional, default empty dict
    margo: ComponentConfig | None
    compose: ComponentConfig | None
    quadlet: ComponentConfig | None


def load_margo_yaml(path: str) -> MargoYaml:
    """Parse margo.yaml file and return fully populated MargoYaml.

    Args:
        path: File path to margo.yaml.

    Returns:
        Parsed and validated MargoYaml.

    Raises:
        ValueError: If file not found, missing required field, or invalid YAML.
    """
    file_path = Path(path)

    # Check file existence
    if not file_path.exists():
        raise ValueError(f"margo.yaml not found: {path}")

    # Load YAML
    try:
        raw = safe_load(file_path.read_text(encoding="utf-8"))
    except YAMLError as e:
        raise ValueError(f"margo.yaml is not valid YAML: {e}") from e

    # Ensure it's a dict
    if not isinstance(raw, dict):
        raise ValueError("margo.yaml is not valid YAML: expected mapping at root")  # noqa: TRY004

    # Validate required fields
    required_fields = ["apiVersion", "name", "description"]
    for field in required_fields:
        if field not in raw:
            raise ValueError(f"margo.yaml missing required field: {field}")

    # Extract required fields
    api_version = raw["apiVersion"]
    name = raw["name"]
    description = raw["description"]

    # Extract optional appVersion (not validated)
    app_version: str | None = raw.get("appVersion")

    # Extract optional annotations (default empty dict)
    annotations: dict[str, str] = raw.get("annotations", {}) or {}

    # Parse optional components
    margo = _parse_component(raw.get("margo"))
    compose = _parse_component(raw.get("compose"))
    quadlet = _parse_component(raw.get("quadlet"))

    return MargoYaml(
        api_version=api_version,
        name=name,
        description=description,
        app_version=app_version,
        annotations=annotations,
        margo=margo,
        compose=compose,
        quadlet=quadlet,
    )


def _parse_component(component_data: object) -> ComponentConfig | None:
    """Parse a component block (margo, compose, or quadlet) and return ComponentConfig or None.

    Args:
        component_data: Raw component data from YAML (dict, None, or other).

    Returns:
        ComponentConfig if present, None otherwise.

    Raises:
        ValueError: If component data is invalid.
    """
    if component_data is None:
        return None

    if not isinstance(component_data, dict):
        raise ValueError("margo.yaml is not valid YAML: component must be a mapping")  # noqa: TRY004

    # directory is required for a component
    if "directory" not in component_data:
        raise ValueError("margo.yaml is not valid YAML: component missing required field 'directory'")

    directory = component_data["directory"]
    version = component_data.get("version")
    repository = component_data.get("repository")

    # Parse variants (optional, defaults to empty list)
    variants_data = component_data.get("variants") or []
    if not isinstance(variants_data, list):
        raise ValueError("margo.yaml is not valid YAML: variants must be a list")  # noqa: TRY004

    variants: list[VariantConfig] = []
    for variant_item in variants_data:
        if not isinstance(variant_item, dict):
            raise ValueError("margo.yaml is not valid YAML: variant item must be a mapping")  # noqa: TRY004
        if "name" not in variant_item or "version" not in variant_item:
            raise ValueError("margo.yaml is not valid YAML: variant missing required field 'name' or 'version'")
        variants.append(VariantConfig(name=variant_item["name"], version=variant_item["version"]))

    return ComponentConfig(
        directory=directory,
        version=version,
        repository=repository,
        variants=tuple(variants),
    )
