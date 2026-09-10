"""Package service: orchestrate offline bundle creation from built artifacts."""

from pathlib import Path
from shutil import rmtree
import tarfile
from tempfile import mkdtemp

from margot import console
from margot.domain.metadata import ComponentConfig, MargoYaml, load_margo_yaml
from margot.domain.models import PackageType
from margot.domain.tags import validate_oci_tag, validate_semver
from margot.infra.filesystem import copy_tree


def _resolve_component_versions(
    component: ComponentConfig | None,
    component_type: PackageType,
) -> list[str]:
    """Resolve all versions for a component (flat or all variants).

    Mirrors the version resolution logic from build.py's _build_flat_component
    and _build_variant_component to ensure consistent version handling.

    Args:
        component: The component config, or None if not defined.
        component_type: COMPOSE or QUADLET.

    Returns:
        List of resolved version strings for this component.
    """
    if component is None:
        return []

    # Flat component: one version
    if not component.variants:
        version = component.version
        if version is None:
            return []  # No version specified, skip
        version = version.replace("+", "_")
        return [version]

    # Variant component: one version per variant
    versions = []
    for variant in component.variants:
        version = variant.version
        if version is None:
            # Variant omits version: use base version + variant suffix
            if component.version is None:
                continue  # Skip if no base version either
            version = f"{component.version}+{component_type.value}-{variant.name}"
        version = version.replace("+", "_")
        versions.append(version)
    return versions


def package(
    package_type: PackageType,
    *,
    project_dir: str = ".",
    build_dir: str = ".dist",
    output: str | None = None,
) -> str:
    """
    Create an offline bundle from built artifacts.

    Bundles already-built margo, compose, and quadlet outputs into a single .tgz file
    for deployment in disconnected/offline environments without registry access.

    Args:
        package_type: PackageType.BUNDLE, or specific type(s) to include.
                     If BUNDLE, all found types are included.
        project_dir: Directory containing margo.yaml (default ".").
        build_dir: Directory containing built artifacts (default ".dist").
        output: Override output bundle path (default: .dist/<version>/<name>-<version>.tgz).

    Returns:
        Path to the created bundle .tgz file.

    Raises:
        ValueError: If build output missing, requested types undefined, or collision detected.
    """
    # Load margo.yaml for metadata
    margo_yaml_path = str(Path(project_dir) / "margo.yaml")
    meta = load_margo_yaml(margo_yaml_path)
    console.info(f"Loaded margo.yaml: {margo_yaml_path}")

    # Resolve margo's version (always uses top-level version)
    margo_version = meta.version
    margo_version = margo_version.replace("+", "_")
    validate_oci_tag(margo_version)
    validate_semver(margo_version)

    # Determine which types to bundle
    types_to_include = _resolve_bundle_types(package_type, meta)

    # Resolve component versions independently
    component_versions = _resolve_component_versions_map(meta, types_to_include)

    # Verify all requested types have been built
    _verify_build_outputs_exist(types_to_include, build_dir, margo_version, component_versions, meta)

    # Detect collisions between components
    _check_for_collisions(meta, types_to_include, build_dir, component_versions)

    # Create the bundle
    bundle_path = _create_bundle(meta, types_to_include, build_dir, margo_version, component_versions, output)

    console.info(f"Bundle created: {bundle_path}")
    return bundle_path


def _resolve_component_versions_map(
    meta: MargoYaml,
    types_to_include: set[PackageType],
) -> dict[PackageType, list[str]]:
    """Resolve all versions for compose and quadlet components.

    Args:
        meta: Loaded margo.yaml.
        types_to_include: Types to resolve versions for.

    Returns:
        Map of PackageType -> list of version strings.
    """
    result = {}
    if PackageType.COMPOSE in types_to_include:
        result[PackageType.COMPOSE] = _resolve_component_versions(meta.compose, PackageType.COMPOSE)
    if PackageType.QUADLET in types_to_include:
        result[PackageType.QUADLET] = _resolve_component_versions(meta.quadlet, PackageType.QUADLET)
    return result


def _resolve_bundle_types(package_type: PackageType, meta: MargoYaml) -> set[PackageType]:
    """Determine which component types to include in the bundle.

    Args:
        package_type: Requested type (BUNDLE to use all found, or specific type).
        meta: Loaded margo.yaml metadata.

    Returns:
        Set of PackageType values to include (only MARGO, COMPOSE, QUADLET).

    Raises:
        ValueError: If a requested type is not defined in margo.yaml.
    """
    # BUNDLE means "use whatever was built" (margo is always present)
    if package_type == PackageType.BUNDLE:
        # Start with margo (always present), then add any defined optional components
        types_found = {PackageType.MARGO}
        if meta.compose is not None:
            types_found.add(PackageType.COMPOSE)
        if meta.quadlet is not None:
            types_found.add(PackageType.QUADLET)
        return types_found

    # Explicit type request — validate it's defined
    if package_type not in (PackageType.MARGO, PackageType.COMPOSE, PackageType.QUADLET):
        raise ValueError(f"Invalid package type for bundling: {package_type}")

    if package_type == PackageType.MARGO:
        return {PackageType.MARGO}
    if package_type == PackageType.COMPOSE:
        if meta.compose is None:
            raise ValueError("compose component not defined in margo.yaml")
        return {PackageType.COMPOSE}
    if package_type == PackageType.QUADLET:
        if meta.quadlet is None:
            raise ValueError("quadlet component not defined in margo.yaml")
        return {PackageType.QUADLET}

    return {PackageType.MARGO}


def _verify_build_outputs_exist(
    types_to_include: set[PackageType],
    build_dir: str,
    margo_version: str,
    component_versions: dict[PackageType, list[str]],
    meta: MargoYaml,
) -> None:
    """Verify that requested build outputs exist on disk.

    Args:
        types_to_include: Types to check.
        build_dir: Build output directory.
        margo_version: Margo's version string.
        component_versions: Map of component type to list of versions.
        meta: Loaded margo.yaml.

    Raises:
        ValueError: If required build output is missing or if margo is not found.
    """
    # Margo is always required, in its own version folder
    margo_path = Path(build_dir) / margo_version / "margo"
    if not margo_path.exists():
        raise ValueError(f"Built margo artifact not found at {margo_path}. Run 'margot build' first.")

    # Check compose: must be in its own version folder(s)
    if PackageType.COMPOSE in types_to_include:
        compose_versions = component_versions.get(PackageType.COMPOSE, [])
        if not compose_versions:
            raise ValueError("compose component not defined in margo.yaml or has no versions")
        for comp_version in compose_versions:
            # Check if at least one tarball exists for this version
            version_path = Path(build_dir) / comp_version
            tarballs = list(version_path.glob(f"{meta.name}-*.tgz"))
            if not tarballs:
                raise ValueError(
                    f"Built compose artifact not found in {version_path}. Run 'margot build' first."
                )

    # Check quadlet: must be in its own version folder(s)
    if PackageType.QUADLET in types_to_include:
        quadlet_versions = component_versions.get(PackageType.QUADLET, [])
        if not quadlet_versions:
            raise ValueError("quadlet component not defined in margo.yaml or has no versions")
        for quad_version in quadlet_versions:
            # Check if at least one tarball exists for this version
            version_path = Path(build_dir) / quad_version
            tarballs = list(version_path.glob(f"{meta.name}-*.tgz"))
            if not tarballs:
                raise ValueError(
                    f"Built quadlet artifact not found in {version_path}. Run 'margot build' first."
                )


def _check_for_collisions(
    meta: MargoYaml,
    types_to_include: set[PackageType],
    build_dir: str,
    component_versions: dict[PackageType, list[str]],
) -> None:
    """Detect if two components would collide when placed in the bundle.

    Collision: same (repository-folder, filename) pair.

    Args:
        meta: Loaded margo.yaml.
        types_to_include: Types to check.
        build_dir: Build output directory.
        component_versions: Map of component type to list of versions.

    Raises:
        ValueError: If a collision is detected.
    """
    seen_collisions: dict[tuple[str, str], tuple[PackageType, str]] = {}

    if PackageType.COMPOSE in types_to_include and meta.compose is not None:
        # Resolve compose repository
        repo = _resolve_component_repository(meta.compose.repository, meta.repository)
        # Check all compose versions for collisions
        for comp_version in component_versions.get(PackageType.COMPOSE, []):
            version_path = Path(build_dir) / comp_version
            for tgz in version_path.glob(f"{meta.name}-*.tgz"):
                filename = tgz.name
                key = (repo, filename)
                if key in seen_collisions:
                    other_type, _other_repo = seen_collisions[key]
                    raise ValueError(
                        f"Collision: {PackageType.COMPOSE.value} and {other_type.value} would both write "
                        f"{repo}/{filename} to the bundle. Resolve the conflict in margo.yaml "
                        f"by using different repository values for each component."
                    )
                seen_collisions[key] = (PackageType.COMPOSE, repo)

    if PackageType.QUADLET in types_to_include and meta.quadlet is not None:
        # Resolve quadlet repository
        repo = _resolve_component_repository(meta.quadlet.repository, meta.repository)
        # Check all quadlet versions for collisions
        for quad_version in component_versions.get(PackageType.QUADLET, []):
            version_path = Path(build_dir) / quad_version
            for tgz in version_path.glob(f"{meta.name}-*.tgz"):
                filename = tgz.name
                key = (repo, filename)
                if key in seen_collisions:
                    other_type, _other_repo = seen_collisions[key]
                    raise ValueError(
                        f"Collision: {PackageType.QUADLET.value} and {other_type.value} would both write "
                        f"{repo}/{filename} to the bundle. Resolve the conflict in margo.yaml "
                        f"by using different repository values for each component."
                    )
                seen_collisions[key] = (PackageType.QUADLET, repo)


def _resolve_component_repository(component_repo: str | None, global_repo: str | None) -> str:
    """Resolve a component's bundle folder path from repository string.

    Args:
        component_repo: Component-level repository field (or None).
        global_repo: Global fallback repository field (or None).

    Returns:
        Repository path (e.g. 'public.ecr.aws/g2n4p2m7/margo').

    Raises:
        ValueError: If no repository is available.
    """
    repo = component_repo or global_repo
    if not repo:
        raise ValueError("No repository configured; cannot determine bundle folder structure")
    # Remove the registry part (everything before the first slash)
    # e.g. 'public.ecr.aws/g2n4p2m7/margo' -> 'g2n4p2m7/margo'
    _, _, rest = repo.partition("/")
    if not rest:
        raise ValueError(f"Cannot parse repository '{repo}' as <registry>/<path>")
    return rest


def _create_bundle(  # noqa: PLR0913
    meta: MargoYaml,
    types_to_include: set[PackageType],
    build_dir: str,
    margo_version: str,
    component_versions: dict[PackageType, list[str]],
    output_override: str | None,
) -> str:
    """Create the bundle tarball.

    Structure:
        <name>-<version>/
          app.yaml (and other margo content)
          <repo1>/
            name-version.tgz
          <repo2>/
            name-version.tgz

    Args:
        meta: Loaded margo.yaml.
        types_to_include: Component types to bundle (already validated).
        build_dir: Build output directory.
        margo_version: Margo's version string (used for bundle root directory).
        component_versions: Map of component type to list of versions.
        output_override: Override output path (or None for default).

    Returns:
        Path to created bundle .tgz file.
    """
    margo_build_path = Path(build_dir) / margo_version
    root_dir_name = f"{meta.name}-{margo_version}"

    # Determine output path
    bundle_path = Path(output_override) if output_override else margo_build_path / f"{meta.name}-{margo_version}.tgz"

    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    # Create temporary staging directory
    tmp_parent = mkdtemp()
    try:
        staging_root = Path(tmp_parent) / root_dir_name

        # 1. Copy margo content recursively to bundle root (drop the margo/ wrapper)
        margo_src = margo_build_path / "margo"
        console.debug(f"Copying margo content from {margo_src}")
        for item in margo_src.iterdir():
            item_dst = staging_root / item.name
            if item.is_dir():
                copy_tree(str(item), str(item_dst))
            else:
                staging_root.mkdir(parents=True, exist_ok=True)
                # Using Path.write_bytes/read_bytes to copy files
                item_dst.write_bytes(item.read_bytes())
            console.debug(f"Copied {item.name} to bundle root")

        # 2. Copy component tarballs under their respective repository folders
        if PackageType.COMPOSE in types_to_include and meta.compose is not None:
            _add_component_to_bundle(
                staging_root,
                meta.compose.repository,
                meta.repository,
                build_dir,
                meta.name,
                "compose",
                component_versions.get(PackageType.COMPOSE, []),
            )

        if PackageType.QUADLET in types_to_include and meta.quadlet is not None:
            _add_component_to_bundle(
                staging_root,
                meta.quadlet.repository,
                meta.repository,
                build_dir,
                meta.name,
                "quadlet",
                component_versions.get(PackageType.QUADLET, []),
            )

        # 3. Create the final tarball
        _write_bundle_tarball(staging_root, bundle_path, root_dir_name)

    finally:
        rmtree(tmp_parent, ignore_errors=True)

    return str(bundle_path)


def _add_component_to_bundle(  # noqa: PLR0913
    staging_root: Path,
    component_repo: str | None,
    global_repo: str | None,
    build_dir: str,
    name: str,
    component_type: str,
    component_versions: list[str],
) -> None:
    """Add a component's built tarballs to the bundle staging directory.

    Looks for the component's tarballs in each of its own version folders
    (since different components can have different versions).

    Args:
        staging_root: Root staging directory.
        component_repo: Component-level repository.
        global_repo: Global repository fallback.
        build_dir: Build output directory.
        name: Package name.
        component_type: 'compose' or 'quadlet'.
        component_versions: List of version strings for this component.
    """
    repo = _resolve_component_repository(component_repo, global_repo)
    repo_dir = staging_root / repo

    # For each version of this component, find and copy its tarball(s)
    for comp_version in component_versions:
        version_path = Path(build_dir) / comp_version
        for tgz in version_path.glob(f"{name}-*.tgz"):
            repo_dir.mkdir(parents=True, exist_ok=True)
            dst = repo_dir / tgz.name
            console.debug(f"Copying {component_type} tarball: {tgz.name} → {repo}/{tgz.name}")
            dst.write_bytes(tgz.read_bytes())


def _write_bundle_tarball(staging_root: Path, bundle_path: Path, root_dir_name: str) -> None:
    """Write the staging directory to a gzip-compressed tarball.

    Args:
        staging_root: Staging root directory (contains root_dir_name/).
        bundle_path: Output tarball path.
        root_dir_name: Name of the root directory inside the tarball.
    """
    console.debug(f"Writing bundle tarball: {bundle_path}")
    with tarfile.open(bundle_path, "w:gz") as tar:
        tar.add(staging_root, arcname=root_dir_name, recursive=True)
    console.debug(f"Bundle tarball written: {bundle_path}")
