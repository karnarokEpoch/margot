"""Margo.yaml dataclasses and YAML parser: pure functions, no I/O."""

from dataclasses import dataclass, field
from pathlib import Path

from yaml import YAMLError, safe_load

_RESERVED_VARIANT_NAMES = {"directory", "repository", "variants", "version", "tag", "ref", "component"}


@dataclass(frozen=True)
class ImageConfig:
    """Literal image replacement configuration for a component."""

    search: str
    replace: str


@dataclass(frozen=True)
class VariantConfig:
    """Configuration for a single variant."""

    name: str
    version: str  # OCI tag as stored (may contain '_')
    component: str | None = None
    image: ImageConfig | None = None


@dataclass(frozen=True)
class ComponentConfig:
    """Configuration for a component (margo, compose, or quadlet)."""

    directory: str
    version: str | None  # None when variants are declared
    repository: str | None  # optional override
    variants: tuple[VariantConfig, ...]  # empty tuple = no variants
    image: ImageConfig | None = None


@dataclass(frozen=True)
class MargoYaml:
    """Parsed margo.yaml file structure."""

    api_version: str  # apiVersion field
    id: str
    name: str
    description: str
    app_version: str | None  # appVersion field (optional, not validated)
    annotations: dict[str, str]  # optional, default empty dict
    margo: ComponentConfig | None
    compose: ComponentConfig | None
    quadlet: ComponentConfig | None
    version: str | None = None
    author: list = field(default_factory=list)
    organization: list = field(default_factory=list)


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

    if not file_path.exists():
        raise ValueError(f"margo.yaml not found: {path}")

    try:
        raw = safe_load(file_path.read_text(encoding="utf-8"))
    except YAMLError as e:
        raise ValueError(f"margo.yaml is not valid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError("margo.yaml is not valid YAML: expected mapping at root")  # noqa: TRY004

    required_fields = ["apiVersion", "id", "name", "description"]
    for required_field in required_fields:
        if required_field not in raw:
            raise ValueError(f"margo.yaml missing required field: {required_field}")

    return MargoYaml(
        api_version=raw["apiVersion"],
        id=raw["id"],
        name=raw["name"],
        description=raw["description"],
        app_version=raw.get("appVersion"),
        annotations=raw.get("annotations", {}) or {},
        margo=_parse_component(raw.get("margo")),
        compose=_parse_component(raw.get("compose")),
        quadlet=_parse_component(raw.get("quadlet")),
        version=raw.get("version"),
        author=raw.get("author") or [],
        organization=raw.get("organization") or [],
    )


def _parse_image(image_data: object) -> ImageConfig | None:
    """Parse and validate an optional image search/replace block."""
    if image_data is None:
        return None
    if not isinstance(image_data, dict):
        raise ValueError("margo.yaml is not valid YAML: image must be a mapping")  # noqa: TRY004

    search = image_data.get("search")
    replace = image_data.get("replace")
    if not isinstance(search, str) or not search:
        raise ValueError("margo.yaml image search must be a non-empty string")
    if not isinstance(replace, str) or not replace:
        raise ValueError("margo.yaml image replace must be a non-empty string")
    return ImageConfig(search=search, replace=replace)


def _parse_component(component_data: object) -> ComponentConfig | None:
    """Parse a component block (margo, compose, or quadlet)."""
    if component_data is None:
        return None

    if not isinstance(component_data, dict):
        raise ValueError("margo.yaml is not valid YAML: component must be a mapping")  # noqa: TRY004
    if "directory" not in component_data:
        raise ValueError("margo.yaml is not valid YAML: component missing required field 'directory'")

    variants_data = component_data.get("variants") or []
    if not isinstance(variants_data, list):
        raise ValueError("margo.yaml is not valid YAML: variants must be a list")  # noqa: TRY004

    variants: list[VariantConfig] = []
    for variant_item in variants_data:
        if not isinstance(variant_item, dict):
            raise ValueError("margo.yaml is not valid YAML: variant item must be a mapping")  # noqa: TRY004
        if "name" not in variant_item or "version" not in variant_item:
            raise ValueError("margo.yaml is not valid YAML: variant missing required field 'name' or 'version'")
        variants.append(
            VariantConfig(
                name=variant_item["name"],
                version=variant_item["version"],
                component=variant_item.get("component"),
                image=_parse_image(variant_item.get("image")),
            )
        )

    for variant in variants:
        if variant.name in _RESERVED_VARIANT_NAMES:
            raise ValueError(f"Variant name '{variant.name}' collides with reserved field name")

    return ComponentConfig(
        directory=component_data["directory"],
        version=component_data.get("version"),
        repository=component_data.get("repository"),
        variants=tuple(variants),
        image=_parse_image(component_data.get("image")),
    )


def build_jinja2_context(meta: MargoYaml, global_repository: str | None = None) -> dict:
    """Build the plain-data context available to app.yaml.jinja templates."""
    manifest: dict[str, object] = {
        "id": meta.id,
        "name": meta.name,
        "version": meta.version or "",
        "appVersion": meta.app_version or "",
        "description": meta.description,
        "annotations": meta.annotations,
        "author": meta.author,
        "organization": meta.organization,
    }

    for component_type, component in (
        ("margo", meta.margo),
        ("compose", meta.compose),
        ("quadlet", meta.quadlet),
    ):
        manifest[component_type] = _build_component_context(meta, component_type, component, global_repository)

    return {"manifest": manifest}


def _build_component_context(
    meta: MargoYaml,
    component_type: str,
    component: ComponentConfig | None,
    global_repository: str | None,
) -> dict[str, object]:
    """Build one component's context dictionary."""
    if component is None:
        return {}

    repository = component.repository or global_repository or ""
    version = component.version or ""
    tag = version.replace("+", "_")
    component_context: dict[str, object] = {
        "directory": component.directory,
        "repository": repository,
        "version": version,
        "tag": tag,
        "ref": f"{repository}:{tag}" if repository and tag else "",
        "variants": [],
    }

    variants = component.variants if component_type != "margo" else ()
    if not variants:
        variants = (VariantConfig(name=meta.name, version=version),)

    variant_contexts: list[dict[str, str]] = []
    for variant in variants:
        variant_tag = variant.version.replace("+", "_")
        variant_context = {
            "name": variant.name,
            "version": variant.version,
            "tag": variant_tag,
            "repository": repository,
            "ref": f"{repository}:{variant_tag}" if repository and variant_tag else "",
            "component": variant.component or f"{meta.id}-{component_type}-{variant.name}",
        }
        variant_contexts.append(variant_context)
        component_context[variant.name] = variant_context

    component_context["variants"] = variant_contexts
    return component_context
