"""Build service: orchestrate artifact building from margo.yaml."""

from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

from jinja2 import Environment, StrictUndefined, UndefinedError

from margot import console
from margot.domain.metadata import ComponentConfig, ImageConfig, MargoYaml, build_jinja2_context, load_margo_yaml
from margot.domain.models import BuildTarget, PackageType
from margot.domain.tags import validate_oci_tag, validate_semver
from margot.infra.filesystem import copy_tree, make_tarball, substitute_placeholders


def build(
    package_type: PackageType,
    *,
    project_dir: str = ".",
    build_dir: str = ".dist",
    version_override: str | None = None,
    variant: str | None = None,
) -> list[BuildTarget]:
    """Build artifacts from margo.yaml for the specified package type(s)."""
    margo_yaml_path = str(Path(project_dir) / "margo.yaml")
    meta = load_margo_yaml(margo_yaml_path)
    console.info(f"Loaded margo.yaml: {margo_yaml_path}")
    placeholders = _build_placeholder_map(meta, version_override)

    if package_type == PackageType.ALL:
        targets = _build_all(meta, project_dir, build_dir, version_override, placeholders)
    elif package_type == PackageType.MARGO:
        targets = [_build_margo(meta, project_dir, build_dir, version_override)]
    elif package_type == PackageType.COMPOSE:
        targets = _build_compose_or_quadlet(
            meta, project_dir, build_dir, version_override, variant, PackageType.COMPOSE, placeholders
        )
    elif package_type == PackageType.QUADLET:
        targets = _build_compose_or_quadlet(
            meta, project_dir, build_dir, version_override, variant, PackageType.QUADLET, placeholders
        )
    else:
        raise ValueError(f"Unsupported package_type: {package_type}")  # pragma: no cover

    console.info(f"Build complete: {len(targets)} target(s).")
    return targets


def _build_all(
    meta: MargoYaml,
    project_dir: str,
    build_dir: str,
    version_override: str | None,
    placeholders: dict[str, str],
) -> list[BuildTarget]:
    """Build all defined components, always including the margo artifact."""
    targets: list[BuildTarget] = [_build_margo(meta, project_dir, build_dir, version_override)]

    for component_type in (PackageType.COMPOSE, PackageType.QUADLET):
        try:
            targets.extend(
                _build_compose_or_quadlet(meta, project_dir, build_dir, version_override, None, component_type, placeholders)
            )
        except ValueError as e:
            if f"{component_type.value} component not defined in margo.yaml" in str(e):
                console.info(f"Skipping {component_type.value}: not defined in margo.yaml")
            else:
                raise
    return targets


def _build_placeholder_map(meta: MargoYaml, version_override: str | None) -> dict[str, str]:
    """Build the supported compose/quadlet placeholder substitutions."""
    margo_version = version_override or meta.version or ""
    compose_version = (
        version_override or (meta.compose.version or (meta.compose.variants[0].version if meta.compose.variants else ""))
        if meta.compose
        else ""
    )
    quadlet_version = (
        version_override or (meta.quadlet.version or (meta.quadlet.variants[0].version if meta.quadlet.variants else ""))
        if meta.quadlet
        else ""
    )
    return {
        "<app_tag>": meta.app_version or "",
        "<margo_tag>": margo_version,
        "<compose_tag>": compose_version,
        "<quadlet_tag>": quadlet_version,
        "<helm_chart_tag>": "",
    }


def _build_margo(
    meta: MargoYaml,
    project_dir: str,
    build_dir: str,
    version_override: str | None,
) -> BuildTarget:
    """Build the margo component, rendering an optional app.yaml.jinja descriptor."""
    version = version_override or meta.version
    validate_oci_tag(version)
    validate_semver(version)
    console.info(f"Building margo: version {version}")

    source_dir = str(Path(project_dir) / meta.directory)
    output_dir = str(Path(build_dir) / version / "margo")
    copy_tree(source_dir, output_dir)

    jinja_file = Path(output_dir) / "app.yaml.jinja"
    static_file = Path(output_dir) / "app.yaml"
    if jinja_file.exists() and static_file.exists():
        raise ValueError("Both app.yaml.jinja and app.yaml found in margo source directory — use one or the other, not both.")
    if jinja_file.exists():
        try:
            environment = Environment(undefined=StrictUndefined)  # noqa: S701
            rendered = environment.from_string(jinja_file.read_text(encoding="utf-8")).render(
                build_jinja2_context(meta, global_repository=meta.repository)
            )
        except UndefinedError as e:
            raise ValueError(f"Unresolved Jinja2 variable in app.yaml.jinja: {e}") from e
        static_file.write_text(rendered, encoding="utf-8")
        jinja_file.unlink()
    elif not static_file.exists():
        raise ValueError("No app.yaml or app.yaml.jinja found in margo source directory.")

    console.info(f"Margo built: {output_dir}")
    return BuildTarget(PackageType.MARGO, None, version, source_dir, output_dir, output_dir)


def _build_compose_or_quadlet(  # noqa: PLR0913
    meta: MargoYaml,
    project_dir: str,
    build_dir: str,
    version_override: str | None,
    variant: str | None,
    component_type: PackageType,
    placeholders: dict[str, str],
) -> list[BuildTarget]:
    """Build compose or quadlet component(s), supporting flat and variant layouts."""
    component = meta.compose if component_type == PackageType.COMPOSE else meta.quadlet
    if component is None:
        raise ValueError(f"{component_type.value} component not defined in margo.yaml")
    if not component.variants:
        return _build_flat_component(
            meta, component, project_dir, build_dir, version_override, variant, component_type, placeholders
        )
    return _build_variant_component(
        meta, component, project_dir, build_dir, version_override, variant, component_type, placeholders
    )


def _build_flat_component(  # noqa: PLR0913
    meta: MargoYaml,
    component: ComponentConfig,
    project_dir: str,
    build_dir: str,
    version_override: str | None,
    variant: str | None,
    component_type: PackageType,
    placeholders: dict[str, str],
) -> list[BuildTarget]:
    """Build a component with a flat layout."""
    component_name = component_type.value
    if variant is not None:
        raise ValueError(f"no variants declared in margo.yaml; --variant not supported for {component_name}")
    version = version_override or component.version
    if version is None:
        raise ValueError(f"{component_name} version not specified and no version_override provided")
    validate_oci_tag(version)
    validate_semver(version)
    console.info(f"Building {component_name}: version {version}")

    source_dir = str(Path(project_dir) / component.directory)
    output_dir = str(Path(build_dir) / version)
    output_path = str(Path(output_dir) / f"{meta.name}-{version}.tgz")
    image_pair = _render_image_pair(meta, component.image)
    tmp_parent = mkdtemp()
    tmp_dir = str(Path(tmp_parent) / "content")
    try:
        copy_tree(source_dir, tmp_dir)
        substitute_placeholders(tmp_dir, placeholders, image_config=image_pair)
        make_tarball(tmp_dir, output_path, meta.name)
        console.info(f"{component_name} built: {output_path}")
    finally:
        rmtree(tmp_parent, ignore_errors=True)
    return [BuildTarget(component_type, None, version, source_dir, output_dir, output_path)]


def _render_image_pair(meta: MargoYaml, image: ImageConfig | None) -> tuple[str, str] | None:
    """Render an optional image replacement template with the manifest context."""
    if image is None:
        return None
    try:
        rendered_replace = Environment(undefined=StrictUndefined).from_string(image.replace).render(  # noqa: S701
            build_jinja2_context(meta, global_repository=meta.repository)
        )
    except UndefinedError as e:
        raise ValueError(f"Unresolved Jinja2 variable in image.replace: {e}") from e
    return image.search, rendered_replace


def _build_variant_component(  # noqa: PLR0913
    meta: MargoYaml,
    component: ComponentConfig,
    project_dir: str,
    build_dir: str,
    version_override: str | None,
    variant: str | None,
    component_type: PackageType,
    placeholders: dict[str, str],
) -> list[BuildTarget]:
    """Build one or all variants of a component."""
    component_name = component_type.value
    if variant is None:
        variants_to_build = component.variants
    else:
        variants_to_build = tuple(item for item in component.variants if item.name == variant)
        if not variants_to_build:
            raise ValueError(f"variant '{variant}' not declared in margo.yaml")

    targets: list[BuildTarget] = []
    for current_variant in variants_to_build:
        version = version_override or current_variant.version
        if version is None:
            if component.version is None:
                raise ValueError(
                    f"{component_name} base version is required when variant '{current_variant.name}' omits version"
                )
            version = f"{component.version}+{component_type.value}-{current_variant.name}"
        version = version.replace("+", "_")
        validate_oci_tag(version)
        validate_semver(version)
        console.info(f"Building {component_name} variant '{current_variant.name}': version {version}")
        source_dir = str(Path(project_dir) / component.directory / current_variant.name)
        output_dir = str(Path(build_dir) / version)
        output_path = str(Path(output_dir) / f"{meta.name}-{version}.tgz")
        effective_image = current_variant.image if current_variant.image is not None else component.image
        image_pair = _render_image_pair(meta, effective_image)
        tmp_parent = mkdtemp()
        tmp_dir = str(Path(tmp_parent) / "content")
        try:
            copy_tree(source_dir, tmp_dir)
            substitute_placeholders(tmp_dir, placeholders, image_config=image_pair)
            make_tarball(tmp_dir, output_path, meta.name)
            console.info(f"{component_name} variant '{current_variant.name}' built: {output_path}")
        finally:
            rmtree(tmp_parent, ignore_errors=True)
        targets.append(BuildTarget(component_type, current_variant.name, version, source_dir, output_dir, output_path))
    return targets
