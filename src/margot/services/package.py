"""Package service: orchestrate offline bundle creation from built artifacts."""

from hashlib import sha256
from json import dumps as json_dumps
from json import load as json_load
from pathlib import Path
from shutil import rmtree
from tarfile import open as tar_open
from tempfile import mkdtemp
from typing import Any

from yaml import YAMLError, safe_load

from margot import console
from margot.domain.metadata import ComponentConfig, MargoYaml, load_margo_yaml
from margot.domain.models import PackageType
from margot.domain.tags import validate_oci_tag, validate_semver
from margot.domain.uri import extract_hostname, validate_uri
from margot.infra.credentials import CredentialsExpiredError, check_credentials
from margot.infra.filesystem import copy_tree
from margot.infra.oci import OciRegistryError, OrasClient


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


def _discover_image_references_compose(tgz_path: str) -> list[str]:
    """Discover image references from a compose component archive.

    Extracts compose.yml or compose.yaml from the tgz, parses the YAML,
    and extracts all services[*].image values. Deduplicates and maintains
    order of first appearance.

    Args:
        tgz_path: Path to the component .tgz file.

    Returns:
        List of deduplicated image references in order of first appearance.
    """
    try:
        compose_data = _load_compose_from_tgz(tgz_path)
        if not compose_data:
            return []
        return _extract_images_from_compose(compose_data)
    except YAMLError as e:
        console.debug(f"Error discovering compose images from {tgz_path}: {e}")
        return []


def _load_compose_from_tgz(tgz_path: str) -> dict[str, Any] | None:
    """Load compose.yml or compose.yaml from a tgz archive.

    Args:
        tgz_path: Path to the .tgz file.

    Returns:
        The parsed YAML dict, or None if not found/invalid.
    """
    try:
        with tar_open(tgz_path, "r:gz") as tar:
            # Try to find compose.yml or compose.yaml
            for member in tar.getmembers():
                if member.name in ("compose.yml", "compose.yaml"):
                    f = tar.extractfile(member)
                    if f is None:
                        return None
                    return safe_load(f.read())
    except YAMLError:
        pass
    return None


def _extract_images_from_compose(compose_data: dict[str, Any]) -> list[str]:
    """Extract image references from parsed compose data.

    Args:
        compose_data: The parsed YAML dict.

    Returns:
        List of deduplicated image references.
    """
    images = []
    seen = set()

    if not isinstance(compose_data, dict):
        return []

    services = compose_data.get("services", {})
    if not isinstance(services, dict):
        return []

    for service_config in services.values():
        if not isinstance(service_config, dict):
            continue
        image = service_config.get("image")
        if isinstance(image, str) and image and image not in seen:
            images.append(image)
            seen.add(image)

    return images


def _discover_image_references_quadlet(tgz_path: str) -> list[str]:  # noqa: C901
    """Discover image references from a quadlet component archive.

    Extracts all .container files from the tgz, parses each file for
    [Container] sections, and extracts Image= values from those sections only.
    Ignores Image= outside of [Container] sections and in comments.
    Deduplicates and maintains order of first appearance.

    Args:
        tgz_path: Path to the component .tgz file.

    Returns:
        List of deduplicated image references in order of first appearance.
    """
    images = []
    seen = set()

    try:
        with tar_open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.name.endswith(".container"):
                    continue

                f = tar.extractfile(member)
                if f is None:
                    continue

                content = f.read().decode("utf-8", errors="ignore")
                in_container_section = False

                for line in content.split("\n"):
                    stripped = line.strip()

                    # Check for section headers
                    if stripped.startswith("["):
                        in_container_section = stripped == "[Container]"
                        continue

                    # Only process Image= inside [Container] sections
                    if not in_container_section:
                        continue

                    # Skip comments
                    if stripped.startswith("#"):
                        continue

                    # Look for Image= assignment
                    if stripped.startswith("Image="):
                        image = stripped[6:].strip()
                        if image and image not in seen:
                            images.append(image)
                            seen.add(image)

    except OSError as e:
        console.debug(f"Error discovering quadlet images from {tgz_path}: {e}")

    return images


def _create_oci_image_layout_tar(
    image_ref: str,
    manifest: dict[str, Any],
    oras_client: OrasClient,
    output_tar_path: str,
) -> None:
    """Create an OCI image-layout tar from a pulled image manifest and blobs.

    Creates a valid OCI image layout (oci-layout, index.json, blobs/sha256/*)
    by pulling all referenced blobs via the OrasClient and assembling them.
    Handles both single-platform manifests and multi-arch indexes, pulling
    all platforms by default.

    Args:
        image_ref: The image reference (e.g. 'nginx:latest'), used for logging.
        manifest: The OCI manifest dict (can be a single manifest or an index).
        oras_client: OrasClient instance to download blobs.
        output_tar_path: Path to write the output OCI layout tar.

    Raises:
        ValueError: If the manifest structure is invalid.
        OciRegistryError: If blob download or verification fails.
    """
    temp_dir = Path(mkdtemp())
    try:
        blobs_dir = temp_dir / "blobs" / "sha256"
        blobs_dir.mkdir(parents=True)

        media_type = manifest.get("mediaType", "")

        # Determine if this is an index or a single manifest
        is_index = "index" in media_type

        if is_index:
            # Multi-platform index: collect all child manifests
            child_manifests = []
            manifests_list = manifest.get("manifests", [])

            for child_descriptor in manifests_list:
                child_digest = child_descriptor.get("digest", "")
                console.debug(f"Pulling child manifest {child_digest} from index")

                # Download the child manifest blob
                manifest_blob_filename = child_digest.split(":")[-1]
                manifest_blob_path = blobs_dir / manifest_blob_filename
                oras_client.download_blob(image_ref, child_digest, str(manifest_blob_path))

                # Verify blob digest
                _verify_blob_digest(manifest_blob_path, child_digest)

                # Parse the child manifest to get config and layers
                with manifest_blob_path.open() as f:
                    child_manifest = json_load(f)

                child_manifests.append((child_descriptor, child_manifest))

            # Download all config and layer blobs from all child manifests
            for _child_descriptor, child_manifest in child_manifests:
                _download_manifest_blobs(
                    child_manifest,
                    oras_client,
                    image_ref,
                    blobs_dir,
                )

            # Build index.json pointing to all child manifests
            index_json = {
                "schemaVersion": 2,
                "mediaType": media_type,
                "manifests": manifests_list,
            }
        else:
            # Single-platform manifest
            _download_manifest_blobs(manifest, oras_client, image_ref, blobs_dir)

            # Build index.json pointing to this single manifest
            manifest_digest = manifest.get("digest") or _compute_manifest_digest(manifest)
            # Size of the manifest serialized as JSON
            manifest_json_str = json_dumps(manifest, separators=(",", ":"), sort_keys=True)
            manifest_size = len(manifest_json_str.encode("utf-8"))

            index_json = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": media_type,
                        "digest": manifest_digest,
                        "size": manifest_size,
                    }
                ],
            }

        # Write oci-layout file (must be valid JSON)
        oci_layout = {"imageLayoutVersion": "1.0.0"}
        (temp_dir / "oci-layout").write_text(json_dumps(oci_layout))

        # Write index.json (must be valid JSON)
        (temp_dir / "index.json").write_text(json_dumps(index_json))

        # Create the final tarball
        with tar_open(output_tar_path, "w") as tar:
            tar.add(temp_dir, arcname=".", recursive=True)

        console.debug(f"Created OCI image layout tar: {output_tar_path}")

    finally:
        rmtree(temp_dir, ignore_errors=True)


def _verify_blob_digest(blob_path: Path, expected_digest: str) -> None:
    """Verify that a downloaded blob matches its expected digest.

    Args:
        blob_path: Path to the blob file.
        expected_digest: Expected digest in format 'sha256:...' or similar.

    Raises:
        OciRegistryError: If the digest does not match.
    """
    # Parse the expected digest
    if ":" not in expected_digest:
        msg = f"Invalid digest format: {expected_digest}"
        raise OciRegistryError(msg)

    algo, expected_hex = expected_digest.split(":", 1)

    # Compute actual digest
    if algo == "sha256":
        actual_hash = sha256(blob_path.read_bytes()).hexdigest()
    else:
        msg = f"Unsupported digest algorithm: {algo}"
        raise OciRegistryError(msg)

    if actual_hash != expected_hex:
        msg = f"Blob digest mismatch: {blob_path.name}. Expected {expected_digest}, got {algo}:{actual_hash}"
        raise OciRegistryError(msg)


def _download_manifest_blobs(
    manifest: dict[str, Any],
    oras_client: OrasClient,
    image_ref: str,
    blobs_dir: Path,
) -> None:
    """Download config and layer blobs for a manifest.

    Args:
        manifest: The OCI manifest dict.
        oras_client: OrasClient instance.
        image_ref: Image reference for logging.
        blobs_dir: Directory to store blobs.
    """
    # Download config blob
    config = manifest.get("config", {})
    config_digest = config.get("digest", "")
    if config_digest:
        console.debug(f"Downloading config blob {config_digest}")
        config_blob_filename = config_digest.split(":")[-1]
        config_blob_path = blobs_dir / config_blob_filename
        oras_client.download_blob(image_ref, config_digest, str(config_blob_path))
        _verify_blob_digest(config_blob_path, config_digest)

    # Download layer blobs
    layers = manifest.get("layers", [])
    for layer in layers:
        layer_digest = layer.get("digest", "")
        if layer_digest:
            console.debug(f"Downloading layer blob {layer_digest}")
            layer_blob_filename = layer_digest.split(":")[-1]
            layer_blob_path = blobs_dir / layer_blob_filename
            oras_client.download_blob(image_ref, layer_digest, str(layer_blob_path))
            _verify_blob_digest(layer_blob_path, layer_digest)


def _compute_manifest_digest(manifest: dict[str, Any]) -> str:
    """Compute the SHA256 digest of a manifest dict.

    Args:
        manifest: The manifest dict.

    Returns:
        The digest in the format 'sha256:...' (computed from JSON).
    """
    manifest_json = json_dumps(manifest, separators=(",", ":"), sort_keys=True)
    digest = sha256(manifest_json.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def package(
    package_type: PackageType,
    *,
    project_dir: str = ".",
    build_dir: str = ".dist",
    output: str | None = None,
    include_images: bool = True,
) -> str:
    """
    Create an offline bundle from built artifacts.

    Bundles already-built margo, compose, and quadlet outputs into a single .tgz file
    for deployment in disconnected/offline environments without registry access.

    By default, also discovers and includes container images referenced by compose/quadlet
    content as OCI image-layout tars in the bundle's images/ folder.

    Args:
        package_type: PackageType.BUNDLE, or specific type(s) to include.
                     If BUNDLE, all found types are included.
        project_dir: Directory containing margo.yaml (default ".").
        build_dir: Directory containing built artifacts (default ".dist").
        output: Override output bundle path (default: .dist/<version>/<name>-<version>.tgz).
        include_images: Whether to discover and bundle referenced container images
                       (default True). Set to False to restore Item 2's pure-local
                       no-network behavior.

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

    # If including images, check credentials first (before any network access)
    if include_images:
        console.info("Checking credentials before image discovery...")

    # Create the bundle
    bundle_path = _create_bundle(
        meta,
        types_to_include,
        build_dir,
        margo_version,
        component_versions,
        output,
        include_images=include_images,
    )

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
                raise ValueError(f"Built compose artifact not found in {version_path}. Run 'margot build' first.")

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
                raise ValueError(f"Built quadlet artifact not found in {version_path}. Run 'margot build' first.")


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
    include_images: bool = True,
) -> str:
    """Create the bundle tarball.

    Structure:
        <name>-<version>/
          app.yaml (and other margo content)
          [images/]
            image1_ref.tar
            image2_ref.tar
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
        include_images: Whether to discover and include container images (default True).

    Returns:
        Path to created bundle .tgz file.

    Raises:
        CredentialsExpiredError: If a registry credential has expired.
        OciRegistryError: If pulling an image fails.
    """
    margo_build_path = Path(build_dir) / margo_version
    root_dir_name = f"{meta.id}-{margo_version}"

    # Determine output path
    bundle_path = Path(output_override) if output_override else margo_build_path / f"{meta.id}-{margo_version}.tgz"

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

        # 3. Discover and include container images if requested and configured
        if include_images and _has_image_configuration(meta, types_to_include):
            try:
                _discover_and_include_images(
                    staging_root,
                    types_to_include,
                    build_dir,
                    meta,
                    component_versions,
                )
            except (CredentialsExpiredError, OciRegistryError):
                # Image pull failed; clean up staging and re-raise
                console.debug("Image discovery/pull failed, cleaning up staging directory")
                rmtree(tmp_parent, ignore_errors=True)
                raise

        # 4. Create the final tarball
        _write_bundle_tarball(staging_root, bundle_path, root_dir_name)

    finally:
        rmtree(tmp_parent, ignore_errors=True)

    return str(bundle_path)


def _has_image_configuration(meta: MargoYaml, types_to_include: set[PackageType]) -> bool:
    """Check if any component/variant has image configuration.

    Args:
        meta: Loaded margo.yaml.
        types_to_include: Component types to check.

    Returns:
        True if any component or variant has image configuration.
    """
    if PackageType.COMPOSE in types_to_include and meta.compose is not None:
        if meta.compose.image is not None:
            return True
        if meta.compose.variants and any(v.image is not None for v in meta.compose.variants):
            return True

    if PackageType.QUADLET in types_to_include and meta.quadlet is not None:
        if meta.quadlet.image is not None:
            return True
        if meta.quadlet.variants and any(v.image is not None for v in meta.quadlet.variants):
            return True

    return False


def _discover_and_include_images(  # noqa: C901, PLR0912, PLR0915
    staging_root: Path,
    types_to_include: set[PackageType],
    build_dir: str,
    meta: MargoYaml,
    component_versions: dict[PackageType, list[str]],
) -> None:
    """Discover container images from compose/quadlet and include them in the bundle.

    Only processes components/variants that have image configuration. If no image
    configuration exists, this function returns early without creating the images/
    directory or making any registry calls.

    Reads built component archives, discovers image references, validates them,
    checks registry credentials, pulls manifests and layers, and saves each as
    an OCI image-layout tar under images/ folder.

    Args:
        staging_root: Root of the bundle staging directory.
        types_to_include: Component types to process.
        build_dir: Build output directory.
        meta: Loaded margo.yaml.
        component_versions: Map of component type to list of versions.

    Raises:
        CredentialsExpiredError: If a registry credential has expired.
        OciRegistryError: If pulling an image fails.
    """
    # Early exit if no image configuration exists anywhere
    if not _has_image_configuration(meta, types_to_include):
        console.debug("No image configuration found; skipping image discovery")
        return

    images_dir = staging_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    discovered_refs = set()  # Track unique refs to avoid duplicate pulls

    # Check if compose has image configuration
    compose_has_image_config = (
        PackageType.COMPOSE in types_to_include
        and meta.compose is not None
        and (
            meta.compose.image is not None
            or (meta.compose.variants and any(v.image is not None for v in meta.compose.variants))
        )
    )

    # Discover images from compose components only if configured
    if compose_has_image_config:
        for comp_version in component_versions.get(PackageType.COMPOSE, []):
            version_path = Path(build_dir) / comp_version
            for tgz in version_path.glob(f"{meta.name}-*.tgz"):
                console.debug(f"Discovering compose images in {tgz.name}")
                refs = _discover_image_references_compose(str(tgz))
                for ref in refs:
                    if ref not in discovered_refs:
                        discovered_refs.add(ref)
                        console.info(f"Found image reference: {ref}")

    # Check if quadlet has image configuration
    quadlet_has_image_config = (
        PackageType.QUADLET in types_to_include
        and meta.quadlet is not None
        and (
            meta.quadlet.image is not None
            or (meta.quadlet.variants and any(v.image is not None for v in meta.quadlet.variants))
        )
    )

    # Discover images from quadlet components only if configured
    if quadlet_has_image_config:
        for quad_version in component_versions.get(PackageType.QUADLET, []):
            version_path = Path(build_dir) / quad_version
            for tgz in version_path.glob(f"{meta.name}-*.tgz"):
                console.debug(f"Discovering quadlet images in {tgz.name}")
                refs = _discover_image_references_quadlet(str(tgz))
                for ref in refs:
                    if ref not in discovered_refs:
                        discovered_refs.add(ref)
                        console.info(f"Found image reference: {ref}")

    if not discovered_refs:
        console.debug("No image references found in configured components")
        return

    # Validate and check credentials for all unique registries before pulling any images
    registry_clients: dict[str, OrasClient] = {}
    for ref in discovered_refs:
        try:
            validate_uri(ref)
        except ValueError as e:
            msg = f"Invalid image reference: {ref}: {e}"
            raise OciRegistryError(msg) from e

        try:
            hostname = extract_hostname(ref)
        except ValueError as e:
            msg = f"Cannot extract hostname from image reference {ref}: {e}"
            raise OciRegistryError(msg) from e

        # Check credentials once per unique registry
        if hostname not in registry_clients:
            console.debug(f"Checking credentials for registry: {hostname}")
            try:
                check_credentials(hostname)
            except CredentialsExpiredError:
                console.fatal(f"Credentials for {hostname} have expired.")
                raise

            # Initialize client for this hostname (will load stored credentials)
            registry_clients[hostname] = OrasClient(hostname=hostname)
            console.debug(f"Initialized OrasClient for {hostname}")

    # Pull and materialize each image
    pulled_images: dict[str, str] = {}  # Track ref -> tar_path for deduplication
    failed_pulls: list[tuple[str, Exception]] = []

    for ref in discovered_refs:
        if ref in pulled_images:
            # Already pulled this exact ref (deduplicated)
            continue

        hostname = extract_hostname(ref)
        oras_client = registry_clients[hostname]

        try:
            # Create a safe deterministic filename from the image ref
            # nginx:latest -> nginx_latest.tar
            # public.ecr.aws/org/repo:1.0 -> public_ecr_aws_org_repo_1_0.tar
            safe_filename = ref.replace("/", "_").replace(":", "_").replace(".", "_") + ".tar"
            image_tar_path = images_dir / safe_filename

            console.info(f"Pulling image: {ref}")

            # Get the manifest (handles both single-arch and multi-arch)
            manifest = oras_client.get_manifest(ref)

            # Create OCI image layout tar with all blobs
            _create_oci_image_layout_tar(ref, manifest, oras_client, str(image_tar_path))

            console.info(f"Pulled and materialized: {ref} → {safe_filename}")
            pulled_images[ref] = str(image_tar_path)

        except (OciRegistryError, CredentialsExpiredError) as e:
            console.warning(f"Failed to pull image {ref}: {e}")
            failed_pulls.append((ref, e))
        except Exception as e:  # noqa: BLE001
            console.warning(f"Unexpected error pulling image {ref}: {e}")
            failed_pulls.append((ref, e))

    # If any pulls failed, abort the entire package operation
    if failed_pulls:
        msg = f"Failed to pull {len(failed_pulls)} image(s): "
        refs_str = ", ".join(ref for ref, _ in failed_pulls)
        console.fatal(f"{msg}{refs_str}")
        raise OciRegistryError(msg + refs_str)

    console.info(f"Successfully pulled and materialized {len(pulled_images)} unique image(s)")


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
    with tar_open(bundle_path, "w:gz") as tar:
        tar.add(staging_root, arcname=root_dir_name, recursive=True)
    console.debug(f"Bundle tarball written: {bundle_path}")
