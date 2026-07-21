"""Build service: orchestrate artifact building from margo.yaml."""

from pathlib import Path
import shutil
import tempfile

from margot import console
from margot.domain.metadata import ComponentConfig, MargoYaml, load_margo_yaml
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
    """
    Build artifacts from margo.yaml for the specified package type(s).

    Steps:
    1. Load margo.yaml from project_dir.
    2. Resolve build targets based on package_type.
    3. For each target, call appropriate builder helper.
    4. Return list of BuildTarget describing what was built.

    Args:
        package_type: PackageType.MARGO, COMPOSE, QUADLET, or ALL.
        project_dir: Directory containing margo.yaml (default ".").
        build_dir: Output root directory (default ".dist").
        version_override: Override all component versions (optional).
        variant: For COMPOSE/QUADLET, build specific variant only (optional).

    Returns:
        List of BuildTarget objects representing built artifacts.

    Raises:
        ValueError: If margo.yaml not found, invalid, or build fails.
    """
    # Step 1: Load margo.yaml
    margo_yaml_path = str(Path(project_dir) / "margo.yaml")
    meta = load_margo_yaml(margo_yaml_path)
    console.info(f"Loaded margo.yaml: {margo_yaml_path}")

    # Build placeholder map once (used by all builders)
    placeholders = _build_placeholder_map(meta, version_override)

    # Step 2 & 3: Resolve and build targets
    targets: list[BuildTarget] = []

    if package_type == PackageType.ALL:
        targets = _build_all(meta, project_dir, build_dir, version_override, placeholders)
    elif package_type == PackageType.MARGO:
        targets.append(_build_margo(meta, project_dir, build_dir, version_override, placeholders))
    elif package_type == PackageType.COMPOSE:
        targets.extend(
            _build_compose_or_quadlet(meta, project_dir, build_dir, version_override, variant, PackageType.COMPOSE, placeholders)
        )
    elif package_type == PackageType.QUADLET:
        targets.extend(
            _build_compose_or_quadlet(meta, project_dir, build_dir, version_override, variant, PackageType.QUADLET, placeholders)
        )
    else:
        raise ValueError(f"Unsupported package_type: {package_type}")

    console.info(f"Build complete: {len(targets)} target(s).")
    return targets


def _build_all(
    meta: MargoYaml,
    project_dir: str,
    build_dir: str,
    version_override: str | None,
    placeholders: dict[str, str],
) -> list[BuildTarget]:
    """Build all components, skipping any not defined in margo.yaml."""
    targets: list[BuildTarget] = []

    try:
        targets.append(_build_margo(meta, project_dir, build_dir, version_override, placeholders))
    except ValueError as e:
        if "not defined in margo.yaml" in str(e):
            console.info("Skipping margo: not defined in margo.yaml")
        else:
            raise

    try:
        targets.extend(
            _build_compose_or_quadlet(
                meta, project_dir, build_dir, version_override, None, PackageType.COMPOSE, placeholders
            )
        )
    except ValueError as e:
        if "not defined in margo.yaml" in str(e):
            console.info("Skipping compose: not defined in margo.yaml")
        else:
            raise

    try:
        targets.extend(
            _build_compose_or_quadlet(
                meta, project_dir, build_dir, version_override, None, PackageType.QUADLET, placeholders
            )
        )
    except ValueError as e:
        if "not defined in margo.yaml" in str(e):
            console.info("Skipping quadlet: not defined in margo.yaml")
        else:
            raise

    return targets


def _build_placeholder_map(meta: MargoYaml, version_override: str | None) -> dict[str, str]:
    """
    Build the substitution placeholder dict from component versions.

    Args:
        meta: Parsed MargoYaml.
        version_override: Override all versions with this value (optional).

    Returns:
        Dict mapping placeholder strings to replacement values.
    """
    # Resolve component versions
    margo_version = version_override or (meta.margo.version if meta.margo else "") or ""
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
    placeholders: dict[str, str],
) -> BuildTarget:
    """
    Build margo component.

    Args:
        meta: Parsed MargoYaml.
        project_dir: Project root directory.
        build_dir: Output root directory.
        version_override: Override version (optional).
        placeholders: Substitution map.

    Returns:
        BuildTarget representing the built margo artifact.

    Raises:
        ValueError: If margo component not defined or version invalid.
    """
    if meta.margo is None:
        raise ValueError("margo component not defined in margo.yaml")

    # Resolve version
    version = version_override or meta.margo.version
    if version is None:
        raise ValueError("margo version not specified and no version_override provided")

    # Validate version
    validate_oci_tag(version)
    validate_semver(version)
    console.info(f"Building margo: version {version}")

    # Resolve directories
    source_dir = str(Path(project_dir) / meta.margo.directory)
    output_dir = str(Path(build_dir) / version / "margo")

    # Copy source tree to output
    copy_tree(source_dir, output_dir)

    # Substitute placeholders
    substitute_placeholders(output_dir, placeholders)
    console.info(f"Margo built: {output_dir}")

    return BuildTarget(
        package_type=PackageType.MARGO,
        variant_name=None,
        version=version,
        source_dir=source_dir,
        output_dir=output_dir,
    )


def _build_compose_or_quadlet(  # noqa: PLR0913
    meta: MargoYaml,
    project_dir: str,
    build_dir: str,
    version_override: str | None,
    variant: str | None,
    component_type: PackageType,
    placeholders: dict[str, str],
) -> list[BuildTarget]:
    """
    Build compose or quadlet component(s).

    Handles both flat layout (no variants) and variant-based layouts.

    Args:
        meta: Parsed MargoYaml.
        project_dir: Project root directory.
        build_dir: Output root directory.
        version_override: Override version (optional).
        variant: Specific variant to build (optional, None = all).
        component_type: PackageType.COMPOSE or PackageType.QUADLET.
        placeholders: Substitution map.

    Returns:
        List of BuildTarget objects for built artifacts.

    Raises:
        ValueError: If component not defined, variant not found, or version invalid.
    """
    # Get the component
    component = meta.compose if component_type == PackageType.COMPOSE else meta.quadlet
    if component is None:
        component_name = component_type.value
        raise ValueError(f"{component_name} component not defined in margo.yaml")

    if not component.variants:
        # Flat layout (no variants)
        return _build_flat_component(
            meta, component, project_dir, build_dir, version_override, variant, component_type, placeholders
        )

    # Variant layout
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
    """Build component with flat layout (no variants)."""
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

    # Build using temp directory
    tmp_parent = tempfile.mkdtemp()
    tmp_dir = str(Path(tmp_parent) / "content")
    try:
        copy_tree(source_dir, tmp_dir)
        substitute_placeholders(tmp_dir, placeholders)
        make_tarball(tmp_dir, output_path)
        console.info(f"{component_name} built: {output_path}")
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)

    return [
        BuildTarget(
            package_type=component_type,
            variant_name=None,
            version=version,
            source_dir=source_dir,
            output_dir=output_dir,
        )
    ]


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
    """Build component with variant layout."""
    component_name = component_type.value
    targets: list[BuildTarget] = []

    # Determine which variants to build
    if variant is None:
        # Build all variants
        variants_to_build = list(component.variants)
    else:
        # Find specific variant
        matching = [v for v in component.variants if v.name == variant]
        if not matching:
            raise ValueError(f"variant '{variant}' not declared in margo.yaml")
        variants_to_build = matching

    for v in variants_to_build:
        version = version_override or v.version

        validate_oci_tag(version)
        validate_semver(version)
        console.info(f"Building {component_name} variant '{v.name}': version {version}")

        source_dir = str(Path(project_dir) / component.directory / v.name)
        output_dir = str(Path(build_dir) / version)
        output_path = str(Path(output_dir) / f"{meta.name}-{version}.tgz")

        # Build using temp directory
        tmp_parent = tempfile.mkdtemp()
        tmp_dir = str(Path(tmp_parent) / "content")
        try:
            copy_tree(source_dir, tmp_dir)
            substitute_placeholders(tmp_dir, placeholders)
            make_tarball(tmp_dir, output_path)
            console.info(f"{component_name} variant '{v.name}' built: {output_path}")
        finally:
            shutil.rmtree(tmp_parent, ignore_errors=True)

        targets.append(
            BuildTarget(
                package_type=component_type,
                variant_name=v.name,
                version=version,
                source_dir=source_dir,
                output_dir=output_dir,
            )
        )

    return targets
