"""Package service: orchestrate offline bundle creation from built artifacts."""

from pathlib import Path
from shutil import rmtree
import tarfile
from tempfile import mkdtemp

from margot import console
from margot.domain.metadata import MargoYaml, load_margo_yaml
from margot.domain.models import PackageType
from margot.domain.tags import validate_oci_tag, validate_semver
from margot.infra.filesystem import copy_tree


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

    version = meta.version
    version = version.replace("+", "_")
    validate_oci_tag(version)
    validate_semver(version)

    # Determine which types to bundle
    types_to_include = _resolve_bundle_types(package_type, meta)

    # Verify all requested types have been built
    _verify_build_outputs_exist(types_to_include, build_dir, version)

    # Detect collisions between components
    _check_for_collisions(meta, types_to_include, build_dir, version)

    # Create the bundle
    bundle_path = _create_bundle(meta, types_to_include, build_dir, version, output)

    console.info(f"Bundle created: {bundle_path}")
    return bundle_path


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
    version: str,
) -> None:
    """Verify that requested build outputs exist on disk.

    Args:
        types_to_include: Types to check.
        build_dir: Build output directory.
        version: Version string.

    Raises:
        ValueError: If required build output is missing or if margo is not found.
    """
    build_path = Path(build_dir) / version

    # Margo is always required
    margo_path = build_path / "margo"
    if not margo_path.exists():
        raise ValueError(f"Built margo artifact not found at {margo_path}. Run 'margot build' first.")

    # Check optional types: they must exist if listed in types_to_include
    # (They were added by _resolve_bundle_types only if defined in margo.yaml)
    for pkg_type in (PackageType.COMPOSE, PackageType.QUADLET):
        if pkg_type in types_to_include:
            # For this component, check if ANY built tarball exists
            component_tarballs = list(build_path.glob("*-*.tgz"))
            if not component_tarballs:
                raise ValueError(
                    f"Built {pkg_type.value} artifact not found in {build_path}. Run 'margot build' first."
                )


def _check_for_collisions(
    meta: MargoYaml,
    types_to_include: set[PackageType],
    build_dir: str,
    version: str,
) -> None:
    """Detect if two components would collide when placed in the bundle.

    Collision: same (repository-folder, filename) pair.

    Args:
        meta: Loaded margo.yaml.
        types_to_include: Types to check.
        build_dir: Build output directory.
        version: Version string.

    Raises:
        ValueError: If a collision is detected.
    """
    seen_collisions: dict[tuple[str, str], tuple[PackageType, str]] = {}

    if PackageType.COMPOSE in types_to_include and meta.compose is not None:
        # Resolve compose repository
        repo = _resolve_component_repository(meta.compose.repository, meta.repository)
        # Add all compose variant tarballs
        for variant_version in _get_built_component_versions(build_dir, version, "compose", meta.name):
            filename = f"{meta.name}-{variant_version}.tgz"
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
        # Add all quadlet variant tarballs
        for variant_version in _get_built_component_versions(build_dir, version, "quadlet", meta.name):
            filename = f"{meta.name}-{variant_version}.tgz"
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


def _get_built_component_versions(
    build_dir: str,
    version: str,
    _component_type: str,
    name: str,
) -> list[str]:
    """Get all built variant versions of a component.

    Args:
        build_dir: Build output directory.
        version: Base version (for flat layout detection).
        _component_type: 'compose' or 'quadlet' (for logging context).
        name: Package name.

    Returns:
        List of version strings of successfully built components.
    """
    versions = []
    build_path = Path(build_dir) / version
    if build_path.exists():
        # Look for tarballs of this component
        for tgz in build_path.glob(f"{name}-*.tgz"):
            # Extract version from filename (name-VERSION.tgz)
            variant_version = tgz.stem[len(name) + 1 :]  # Remove 'name-' prefix, keep everything else
            versions.append(variant_version)
    return sorted(versions)


def _create_bundle(
    meta: MargoYaml,
    types_to_include: set[PackageType],
    build_dir: str,
    version: str,
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
        version: Version string.
        output_override: Override output path (or None for default).

    Returns:
        Path to created bundle .tgz file.
    """
    build_path = Path(build_dir) / version
    root_dir_name = f"{meta.name}-{version}"

    # Determine output path
    bundle_path = Path(output_override) if output_override else build_path / f"{meta.name}-{version}.tgz"

    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    # Create temporary staging directory
    tmp_parent = mkdtemp()
    try:
        staging_root = Path(tmp_parent) / root_dir_name

        # 1. Copy margo content recursively to bundle root (drop the margo/ wrapper)
        margo_src = build_path / "margo"
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
                staging_root, meta.compose.repository, meta.repository, build_path, meta.name, "compose"
            )

        if PackageType.QUADLET in types_to_include and meta.quadlet is not None:
            _add_component_to_bundle(
                staging_root, meta.quadlet.repository, meta.repository, build_path, meta.name, "quadlet"
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
    build_path: Path,
    name: str,
    component_type: str,
) -> None:
    """Add a component's built tarballs to the bundle staging directory.

    Args:
        staging_root: Root staging directory.
        component_repo: Component-level repository.
        global_repo: Global repository fallback.
        build_path: Build output directory.
        name: Package name.
        component_type: 'compose' or 'quadlet'.
    """
    repo = _resolve_component_repository(component_repo, global_repo)
    repo_dir = staging_root / repo

    # Find all built tarballs for this component
    for tgz in build_path.glob(f"{name}-*.tgz"):
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
