"""Package service: orchestrate offline bundle creation from built artifacts."""

import contextlib
from enum import StrEnum
from hashlib import sha256
from json import dumps as json_dumps
from json import load as json_load
from os import environ, getuid
from pathlib import Path
import platform as platform_module
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

try:
    from podman import PodmanClient
except ImportError:
    PodmanClient = None  # type: ignore[assignment]

try:
    from docker import from_env as docker_from_env
except ImportError:
    docker_from_env = None  # type: ignore[assignment]


class RuntimeLookup(StrEnum):
    """Runtime daemon lookup strategy."""

    AUTO = "auto"
    PODMAN = "podman"
    DOCKER = "docker"
    NONE = "none"


def _validate_runtime_flag(runtime: str) -> None:
    """Validate that runtime flag is one of the allowed values.

    Args:
        runtime: The runtime value to validate.

    Raises:
        ValueError: If runtime is not a valid choice.
    """
    valid = {e.value for e in RuntimeLookup}
    if runtime not in valid:
        msg = f"Invalid runtime: {runtime!r}. Must be one of: {', '.join(sorted(valid))}"
        raise ValueError(msg)


def _resolve_podman_socket_uri() -> str:
    """Resolve the Podman socket URI for rootless Podman daemon.

    Returns the standard rootless Podman socket location:
    - If XDG_RUNTIME_DIR is set: unix://{XDG_RUNTIME_DIR}/podman/podman.sock
    - Otherwise: unix:///run/user/{uid}/podman/podman.sock (systemd user session default)

    Returns:
        The Podman socket URI in the format 'unix://...'

    Raises:
        RuntimeError: If neither XDG_RUNTIME_DIR nor the default path is accessible.
    """
    xdg_runtime_dir = environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime_dir:
        return f"unix://{xdg_runtime_dir}/podman/podman.sock"

    # Fall back to systemd user session default
    uid = getuid()
    return f"unix:///run/user/{uid}/podman/podman.sock"


def _get_host_platform() -> str:
    """Get the host's OS and architecture in OCI format (os/arch).

    Returns:
        Platform string (e.g. 'linux/amd64', 'linux/arm64').
    """
    os_name = platform_module.system().lower()
    machine = platform_module.machine().lower()

    # Normalize machine architecture to OCI standard
    # x86_64 / x86-64 -> amd64
    # aarch64 -> arm64
    # armv7l / armv7 -> arm (variant v7 handled separately)
    # ppc64le -> ppc64le
    # s390x -> s390x
    arch_map = {
        "x86_64": "amd64",
        "x86-64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "arm",
        "armv7": "arm",
        "armv6l": "arm",
        "armv5l": "arm",
        "ppc64le": "ppc64le",
        "s390x": "s390x",
        "riscv64": "riscv64",
    }

    arch = arch_map.get(machine, machine)
    return f"{os_name}/{arch}"


def _export_image_to_oci_archive(
    image: Any,  # noqa: ANN401
    image_ref: str,
    output_dir: str,
    platform_str: str | None = None,
) -> str | None:
    """Export a Podman image object to OCI-archive format.

    Args:
        image: A Podman Image object.
        image_ref: Image reference (for logging and filename generation).
        output_dir: Directory to write exported tar.
        platform_str: Optional platform string (e.g. 'linux/amd64') to include in filename
                     for disambiguating multiple exports of the same ref from a manifest list.

    Returns:
        Path to the exported OCI-archive tar, or None if export fails.
    """
    # Include platform in filename if provided, to avoid collisions when exporting
    # multiple platforms of the same image_ref from a manifest list.
    # e.g. "nginx:latest" with "linux/amd64" → "nginx_latest_linux_amd64.tar"
    safe_ref = image_ref.replace("/", "_").replace(":", "_")
    if platform_str:
        safe_platform = platform_str.replace("/", "_")
        filename = f"{safe_ref}_{safe_platform}.tar"
    else:
        filename = f"{safe_ref}.tar"

    export_path = Path(output_dir) / filename
    console.debug(f"Exporting {image_ref} from Podman to {export_path}")

    try:
        # Call the underlying HTTP client directly with oci-archive format.
        # The podman SDK's Image.save() hardcodes format=docker-archive,
        # but the libpod API endpoint supports oci-archive natively.
        response = image.client.get(
            f"/images/{image.id}/get",
            params={"format": ["oci-archive"]},
            stream=True,
        )
        response.raise_for_status()

        with export_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        console.debug(f"Podman export complete: {export_path}")
        return str(export_path)
    except Exception as e:  # noqa: BLE001
        console.debug(f"Error exporting image from Podman: {e}")
        return None


def _resolve_all_platforms_from_manifest_list(
    image_ref: str,
    output_dir: str,
) -> dict[str, str | None]:
    """Resolve all platforms from a local Podman manifest list.

    Attempts to find a local Podman manifest list for the image reference,
    and for EVERY child entry in that manifest list, resolves its digest
    to a concrete local image and exports it. This is Podman-specific —
    Docker Engine does not have an equivalent local manifest list concept.

    Args:
        image_ref: Image reference (e.g. 'nginx:latest').
        output_dir: Directory to write exported tars.

    Returns:
        Dict mapping platform string (e.g. 'linux/amd64') to path of exported tar,
        or None if that platform's digest could not be resolved locally.
        Empty dict if no manifest list found or reference is invalid.
    """
    if PodmanClient is None:
        return {}

    result: dict[str, str | None] = {}

    try:
        uri = _resolve_podman_socket_uri()
        with PodmanClient(base_url=uri) as client:
            # Check if reference resolves to a manifest list
            if not client.manifests.exists(image_ref):
                console.debug(f"No local manifest list for {image_ref}")
                return result

            console.debug(f"Found local manifest list for {image_ref}, resolving all platforms")
            manifest_list = client.manifests.get(image_ref)
            manifest_entries = manifest_list.attrs.get("manifests", [])

            if not manifest_entries:
                console.debug(f"Manifest list for {image_ref} has no entries")
                return result

            # For EVERY child entry, attempt to resolve and export
            for entry in manifest_entries:
                child_digest = entry.get("digest")
                platform_dict = entry.get("platform", {})

                if not child_digest:
                    console.debug("Manifest entry has no digest, skipping")
                    continue

                platform_str = _platform_descriptor_to_string(platform_dict)
                console.debug(f"Attempting to resolve manifest entry digest {child_digest} for platform {platform_str}")

                try:
                    # Resolve the digest to a concrete local image via images.list().
                    # Note: client.images.get(<digest>) does not work for manifest-list child digests;
                    # it 404s against the real SDK. Use images.list(filters={"digest": ...}) instead.
                    matches = client.images.list(filters={"digest": child_digest})
                    if not matches:
                        console.debug(f"No local image found for manifest entry digest {child_digest}")
                        result[platform_str] = None
                        continue

                    concrete_image = matches[0]
                    export_path = _export_image_to_oci_archive(concrete_image, image_ref, output_dir, platform_str)

                    if export_path:
                        console.debug(
                            f"Successfully resolved {image_ref} child digest {child_digest} "
                            f"({platform_str}) from local image, exported to {export_path}"
                        )
                        result[platform_str] = export_path
                    else:
                        console.debug(f"Failed to export concrete image for digest {child_digest}")
                        result[platform_str] = None
                except Exception as e:  # noqa: BLE001
                    console.debug(f"Failed to resolve child digest {child_digest} to local image: {e}")
                    result[platform_str] = None

            return result

    except Exception as e:  # noqa: BLE001
        console.debug(f"Manifest list lookup failed for {image_ref}: {e}")
        return {}


def _lookup_image_podman(  # noqa: C901, PLR0911, PLR0912, PLR0915
    image_ref: str,
    output_dir: str,
    required: bool = False,
) -> str | None:
    """Look up and export an image from a local Podman daemon.

    Exports the image in OCI-archive format if found, or returns None
    if not found or the socket is unreachable. Falls back to manifest-list
    resolution for images stored locally only as a manifest list wrapper.

    Args:
        image_ref: Image reference (e.g. 'nginx:latest').
        output_dir: Directory to write exported tar.
        required: If True, raise error when socket unreachable. If False, return None.

    Returns:
        Path to the exported OCI-archive tar, or None if not found.

    Raises:
        RuntimeError: If required=True and socket is unreachable.
    """
    if PodmanClient is None:
        if required:
            msg = "Podman SDK not available (install with: pip install podman)"
            raise RuntimeError(msg)
        return None

    try:
        uri = _resolve_podman_socket_uri()
        with PodmanClient(base_url=uri) as client:
            # Try direct image lookup first (fast path)
            try:
                image = client.images.get(image_ref)
                return _export_image_to_oci_archive(image, image_ref, output_dir)
            except Exception as e:  # noqa: BLE001
                console.debug(f"Direct image lookup failed for {image_ref}: {e}")

            # Fallback: check if reference resolves to a manifest list
            try:
                if not client.manifests.exists(image_ref):
                    console.debug(f"Image {image_ref} not found in Podman (not a manifest list)")
                    return None

                console.debug(f"Resolving {image_ref} via local manifest list")
                manifest_list = client.manifests.get(image_ref)
                manifest_entries = manifest_list.attrs.get("manifests", [])

                if not manifest_entries:
                    console.debug(f"Manifest list for {image_ref} has no entries")
                    return None

                # Get host platform
                host_platform = _get_host_platform()
                console.debug(f"Host platform: {host_platform}")

                # Find matching entry for host platform
                matching_digest = None
                matching_platform = None

                for entry in manifest_entries:
                    entry_platform_dict = entry.get("platform", {})
                    console.debug(f"Checking manifest entry platform: {entry_platform_dict}")

                    if _platform_matches_manifest(host_platform, entry_platform_dict):
                        matching_digest = entry.get("digest")
                        matching_platform = entry_platform_dict
                        console.debug(f"Found matching platform entry with digest {matching_digest}")
                        break

                if not matching_digest:
                    # No matching platform in manifest list
                    available_platforms = []
                    for entry in manifest_entries:
                        plat = entry.get("platform", {})
                        if plat:
                            os_name = plat.get("os", "unknown")
                            arch = plat.get("architecture", "unknown")
                            variant = plat.get("variant")
                            if variant:
                                available_platforms.append(f"{os_name}/{arch}/{variant}")
                            else:
                                available_platforms.append(f"{os_name}/{arch}")

                    console.debug(
                        f"No platform match for {host_platform} in manifest list for {image_ref}. "
                        f"Available: {', '.join(available_platforms)}"
                    )
                    return None

                # Try to get the concrete image by digest
                try:
                    # Resolve the digest to a concrete local image via images.list().
                    # Note: client.images.get(<digest>) does not work for manifest-list child digests;
                    # it 404s against the real SDK. Use images.list(filters={"digest": ...}) instead.
                    matches = client.images.list(filters={"digest": matching_digest})
                    if not matches:
                        console.debug(f"No local image found for manifest entry digest {matching_digest}")
                        return None

                    concrete_image = matches[0]
                    export_path = _export_image_to_oci_archive(concrete_image, image_ref, output_dir)
                    if export_path:
                        os_name = matching_platform.get("os", "unknown")
                        arch = matching_platform.get("architecture", "unknown")
                        console.info(
                            f"Resolved {image_ref} via local manifest list "
                            f"(platform match: {os_name}/{arch}), using local copy"
                        )
                    return export_path  # noqa: TRY300
                except Exception as e:  # noqa: BLE001
                    console.debug(f"Failed to get concrete image by digest {matching_digest}: {e}")
                    return None

            except Exception as e:  # noqa: BLE001
                console.debug(f"Manifest list lookup failed for {image_ref}: {e}")
                return None

    except Exception as e:
        if required:
            msg = f"Podman socket unreachable: {e}"
            raise RuntimeError(msg) from e
        console.debug(f"Podman socket unreachable (auto-probe): {e}")
        return None


def _lookup_image_docker(
    image_ref: str,
    output_dir: str,
    required: bool = False,
) -> str | None:
    """Look up and export an image from a local Docker daemon.

    Exports the image as Docker tarball, then normalizes to OCI image-layout format.

    Args:
        image_ref: Image reference (e.g. 'nginx:latest').
        output_dir: Directory to write exported tar.
        required: If True, raise error when socket unreachable. If False, return None.

    Returns:
        Path to the normalized OCI image-layout tar, or None if not found.

    Raises:
        RuntimeError: If required=True and socket is unreachable.
    """
    if docker_from_env is None:
        if required:
            msg = "Docker SDK not available (install with: pip install docker)"
            raise RuntimeError(msg)
        return None

    try:
        client = docker_from_env(timeout=5)
        try:
            image = client.images.get(image_ref)
        except Exception as e:  # noqa: BLE001
            console.debug(f"Image {image_ref} not found in Docker: {e}")
            return None

        # Export image as Docker tarball
        docker_tar_path = Path(output_dir) / f"{image_ref.replace('/', '_').replace(':', '_')}.docker.tar"
        console.debug(f"Exporting {image_ref} from Docker to {docker_tar_path}")

        try:
            with docker_tar_path.open("wb") as f:
                for chunk in image.save():
                    f.write(chunk)
            console.debug(f"Docker export complete: {docker_tar_path}")

            # Normalize Docker tarball to OCI image-layout
            oras_client = OrasClient()
            oci_path = _normalize_docker_tarball_to_oci_layout(
                str(docker_tar_path),
                image_ref,
                output_dir,
                oras_client,
            )
            docker_tar_path.unlink()  # Clean up Docker tarball
            return oci_path  # noqa: TRY300

        except Exception as e:  # noqa: BLE001
            console.debug(f"Error exporting image from Docker: {e}")
            if docker_tar_path.exists():
                docker_tar_path.unlink()
            return None

    except Exception as e:
        if required:
            msg = f"Docker socket unreachable: {e}"
            raise RuntimeError(msg) from e
        console.debug(f"Docker socket unreachable (auto-probe): {e}")
        return None


def _normalize_docker_tarball_to_oci_layout(  # noqa: PLR0915
    docker_tar_path: str,
    image_ref: str,
    output_dir: str,
    oras_client: OrasClient,  # noqa: ARG001
) -> str:
    """Convert Docker tarball to OCI image-layout format.

    Docker's tarball format includes manifest.json and individual layer/config tars.
    This function extracts those and reassembles them into OCI image-layout format,
    translating Docker legacy media types to OCI equivalents and computing real
    sha256 digests for all blobs.

    Args:
        docker_tar_path: Path to Docker tarball.
        image_ref: Image reference for logging.
        output_dir: Directory to write output OCI layout tar.
        oras_client: OrasClient instance (for potential future use).

    Returns:
        Path to the OCI image-layout tar.

    Raises:
        ValueError: If Docker tarball structure is invalid or manifest parsing fails.
    """
    output_path = Path(output_dir) / f"{image_ref.replace('/', '_').replace(':', '_')}.oci.tar"
    console.debug(f"Normalizing Docker tarball to OCI layout: {output_path}")

    temp_dir = Path(mkdtemp())
    try:
        # Extract Docker tarball
        with tar_open(docker_tar_path, "r") as docker_tar:
            docker_tar.extractall(temp_dir, filter="data")

        # Read manifest.json from Docker tarball
        manifest_json_path = temp_dir / "manifest.json"
        if not manifest_json_path.exists():
            msg = f"Docker tarball missing manifest.json: {docker_tar_path}"
            raise ValueError(msg)

        with manifest_json_path.open() as f:
            docker_manifest_list = json_load(f)

        # Docker's manifest.json is a list; we handle single-image case (first entry)
        if not isinstance(docker_manifest_list, list) or not docker_manifest_list:
            msg = "Docker tarball manifest.json is not a non-empty list"
            raise ValueError(msg)

        docker_manifest_entry = docker_manifest_list[0]

        # Read config blob
        config_filename = docker_manifest_entry.get("Config")
        if not config_filename:
            msg = "Docker manifest entry missing Config field"
            raise ValueError(msg)

        config_path = temp_dir / config_filename
        if not config_path.exists():
            msg = f"Docker tarball missing config blob: {config_filename}"
            raise ValueError(msg)

        config_bytes = config_path.read_bytes()
        config_digest = f"sha256:{sha256(config_bytes).hexdigest()}"
        config_media_type = "application/vnd.oci.image.config.v1+json"

        # Translate Docker config media type if present
        config_json = json_load(config_path.open())
        docker_config_media_type = config_json.get("mediaType", "")
        if "vnd.docker" in docker_config_media_type:
            console.debug(f"Translating Docker config media type: {docker_config_media_type}")
            config_media_type = "application/vnd.oci.image.config.v1+json"

        # Read layer blobs and compute digests
        layer_digests = []
        layers_data = docker_manifest_entry.get("Layers", [])

        for layer_filename in layers_data:
            layer_path = temp_dir / layer_filename
            if not layer_path.exists():
                msg = f"Docker tarball missing layer blob: {layer_filename}"
                raise ValueError(msg)

            layer_bytes = layer_path.read_bytes()
            layer_digest = f"sha256:{sha256(layer_bytes).hexdigest()}"

            # Determine layer media type (translate Docker's if needed)
            # Docker layers are typically .tar.gz files
            if layer_filename.endswith(".tar.gz"):
                layer_media_type = "application/vnd.oci.image.layer.v1.tar+gzip"
            else:
                layer_media_type = "application/vnd.oci.image.layer.v1.tar"

            layer_digests.append(
                {
                    "digest": layer_digest,
                    "media_type": layer_media_type,
                    "size": len(layer_bytes),
                    "bytes": layer_bytes,
                }
            )

        # Build OCI manifest
        manifest_dict = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": config_media_type,
                "digest": config_digest,
                "size": len(config_bytes),
            },
            "layers": [
                {
                    "mediaType": layer["media_type"],
                    "digest": layer["digest"],
                    "size": layer["size"],
                }
                for layer in layer_digests
            ],
        }

        manifest_json_str = json_dumps(manifest_dict, separators=(",", ":"), sort_keys=True)
        manifest_bytes = manifest_json_str.encode("utf-8")
        manifest_digest = f"sha256:{sha256(manifest_bytes).hexdigest()}"

        # Create OCI image layout structure
        oci_layout_dir = temp_dir / "oci_layout"
        oci_layout_dir.mkdir(parents=True, exist_ok=True)

        blobs_dir = oci_layout_dir / "blobs" / "sha256"
        blobs_dir.mkdir(parents=True, exist_ok=True)

        # Write config blob
        config_blob_filename = config_digest.rsplit(":", maxsplit=1)[-1]
        (blobs_dir / config_blob_filename).write_bytes(config_bytes)

        # Write layer blobs
        for layer in layer_digests:
            layer_blob_filename = layer["digest"].split(":")[-1]
            (blobs_dir / layer_blob_filename).write_bytes(layer["bytes"])

        # Write manifest blob
        manifest_blob_filename = manifest_digest.rsplit(":", maxsplit=1)[-1]
        (blobs_dir / manifest_blob_filename).write_bytes(manifest_bytes)

        # Write oci-layout file
        oci_layout_file = {
            "imageLayoutVersion": "1.0.0",
        }
        (oci_layout_dir / "oci-layout").write_text(json_dumps(oci_layout_file))

        # Write index.json pointing to the manifest
        index_json = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": manifest_digest,
                    "size": len(manifest_bytes),
                    "annotations": {
                        "org.opencontainers.image.ref.name": image_ref,
                    },
                }
            ],
        }
        (oci_layout_dir / "index.json").write_text(json_dumps(index_json))

        # Create the output OCI layout tar
        with tar_open(output_path, "w") as output_tar:
            output_tar.add(oci_layout_dir, arcname=".", recursive=True)

        console.debug(f"Docker tarball normalized to OCI layout: {output_path}")
        return str(output_path)

    finally:
        rmtree(temp_dir, ignore_errors=True)


def _lookup_image_with_runtime(
    image_ref: str,
    output_dir: str,
    runtime: str,
    oras_client: OrasClient,  # noqa: ARG001
) -> str | None:
    """Look up an image using the specified runtime strategy.

    Implements the lookup precedence:
    - 'auto': try Podman → Docker → return None (registry fallback)
    - 'podman': try Podman only, raise error if unreachable
    - 'docker': try Docker only, raise error if unreachable
    - 'none': return None immediately (registry-only)

    Args:
        image_ref: Image reference (e.g. 'nginx:latest').
        output_dir: Directory to write exported tar.
        runtime: Runtime strategy ('auto', 'podman', 'docker', 'none').
        oras_client: OrasClient instance for future use.

    Returns:
        Path to exported OCI image-layout tar, or None to fall back to registry.

    Raises:
        RuntimeError: If forced daemon (podman/docker) is unreachable.
    """
    _validate_runtime_flag(runtime)

    if runtime == RuntimeLookup.NONE.value:
        return None

    if runtime == RuntimeLookup.PODMAN.value:
        return _lookup_image_podman(image_ref, output_dir, required=True)

    if runtime == RuntimeLookup.DOCKER.value:
        return _lookup_image_docker(image_ref, output_dir, required=True)

    # runtime == 'auto': silent auto-probe
    console.debug(f"Auto-probing for {image_ref}: Podman → Docker → registry")
    console.info(f"Trying local Podman for {image_ref}...")

    # Try Podman first
    result = _lookup_image_podman(image_ref, output_dir, required=False)
    if result is not None:
        console.info(f"Found {image_ref} in Podman, using local copy")
        return result
    console.info("Not found in Podman, trying Docker...")

    # Try Docker second
    console.info(f"Trying local Docker for {image_ref}...")
    result = _lookup_image_docker(image_ref, output_dir, required=False)
    if result is not None:
        console.info(f"Found {image_ref} in Docker, using local copy")
        return result
    console.info("Not found in Docker, falling back to registry...")

    # Fall back to registry
    console.info(f"Falling back to registry for {image_ref}")
    console.debug(f"No local daemon found for {image_ref}, will use registry")
    return None


def _validate_platform(platform_str: str) -> None:
    """Validate that a platform string is in valid os/arch or os/arch/variant format.

    Args:
        platform_str: Platform string (e.g. 'linux/amd64' or 'linux/arm/v7').

    Raises:
        ValueError: If the platform string is malformed.
    """
    parts = platform_str.split("/")
    if len(parts) < 2 or len(parts) > 3:  # noqa: PLR2004
        raise ValueError(f"Invalid platform '{platform_str}': must be in os/arch or os/arch/variant format")
    # Check all parts are non-empty
    if not all(part for part in parts):
        raise ValueError(f"Invalid platform '{platform_str}': must be in os/arch or os/arch/variant format")


def _normalize_platform(platform_str: str) -> str:
    """Normalize a platform string to canonical form.

    Currently just validates and returns as-is (case-sensitive, as per OCI spec).

    Args:
        platform_str: Platform string.

    Returns:
        Normalized platform string.

    Raises:
        ValueError: If the platform string is invalid.
    """
    _validate_platform(platform_str)
    return platform_str


def _platform_matches_manifest(platform_str: str, manifest_platform: dict[str, Any]) -> bool:
    """Check if a requested platform matches a manifest's platform descriptor.

    Args:
        platform_str: Requested platform (e.g. 'linux/amd64' or 'linux/arm/v7').
        manifest_platform: The platform object from an OCI manifest descriptor.
                          E.g. {"os": "linux", "architecture": "amd64", "variant": "v7"}

    Returns:
        True if the platform matches, False otherwise.
    """
    parts = platform_str.split("/")
    os_part = parts[0]
    arch_part = parts[1]
    variant_part = parts[2] if len(parts) > 2 else None  # noqa: PLR2004

    # Check OS
    if manifest_platform.get("os") != os_part:
        return False

    # Check architecture
    if manifest_platform.get("architecture") != arch_part:
        return False

    # Check variant (if requested)
    return not (variant_part is not None and manifest_platform.get("variant") != variant_part)


def _filter_manifests_by_platforms(  # noqa: C901
    manifest: dict[str, Any],
    platforms: list[str],
) -> dict[str, Any]:
    """Filter image manifests/index to only requested platforms.

    Handles both single-arch manifests and multi-arch indexes. Returns the manifest
    unmodified if platforms is empty. For indexes, filters to matching platforms.
    For single-arch manifests, either passes through (if no platform filter) or
    raises a clear error if platforms don't match.

    Args:
        manifest: The OCI image manifest or index dict.
        platforms: List of requested platforms (e.g. ['linux/amd64', 'linux/arm64']).
                  Empty list means "all platforms".

    Returns:
        The (possibly filtered) manifest dict.

    Raises:
        ValueError: If a requested platform is not found in the index, or if a
                   single-arch manifest doesn't match the platform filter.
    """
    # Validate all requested platforms first
    for platform in platforms:
        _validate_platform(platform)

    # If no platform filter, return as-is
    if not platforms:
        return manifest

    media_type = manifest.get("mediaType", "")
    is_index = "index" in media_type

    if not is_index:
        # Single-arch manifest
        # Per spec, platform info may not be present in the manifest itself
        # We can't match a single-arch manifest against platform requests
        # per Item 5 spec: "A single-platform (non-index) image with a
        # non-matching --platform filter = clear error, not silent no-op."
        raise ValueError(
            f"Single-platform image does not support --platform filtering. Requested platforms: {', '.join(platforms)}"
        )

    # Multi-arch index: filter manifests list
    manifests = manifest.get("manifests", [])
    filtered = []

    for manifest_descriptor in manifests:
        manifest_platform = manifest_descriptor.get("platform", {})
        for requested_platform in platforms:
            if _platform_matches_manifest(requested_platform, manifest_platform):
                filtered.append(manifest_descriptor)
                break  # Don't add this manifest twice

    # Verify all requested platforms were found
    if len(filtered) < len(platforms):
        # Build a list of all available platforms for the error message
        available = []
        for desc in manifests:
            plat = desc.get("platform", {})
            if plat:
                os_name = plat.get("os", "unknown")
                arch = plat.get("architecture", "unknown")
                variant = plat.get("variant")
                if variant:
                    available.append(f"{os_name}/{arch}/{variant}")
                else:
                    available.append(f"{os_name}/{arch}")

        raise ValueError(
            f"Requested platform(s) {{{', '.join(platforms)}}} not found in image index. "
            f"Available platforms: {', '.join(available)}"
        )

    # Return filtered index
    result = manifest.copy()
    result["manifests"] = filtered
    return result


def _validate_platform_no_images_exclusion(
    platforms: list[str] | None,
    no_images: bool,
) -> None:
    """Validate that --platform and --no-images are not both set.

    Per Item 5 spec: `--platform` + `--no-images` = mutually pointless:
    fail clearly (nothing to filter), do not silently ignore --platform.

    Args:
        platforms: List of requested platforms (or None/empty).
        no_images: Whether --no-images flag is set.

    Raises:
        ValueError: If both are set.
    """
    if platforms and no_images:
        raise ValueError(
            "--platform and --no-images are mutually exclusive. "
            "--platform filters which platforms to pull, but --no-images skips image "
            "pulling entirely. Use one or the other, not both."
        )


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


def _create_oci_image_layout_tar(  # noqa: PLR0913, PLR0915
    image_ref: str,
    manifest: dict[str, Any],
    oras_client: OrasClient,
    output_tar_path: str,
    platforms: list[str] | None = None,
    pre_downloaded_blobs: dict[str, str] | None = None,
) -> None:
    """Create an OCI image-layout tar from a pulled image manifest and blobs.

    Creates a valid OCI image layout (oci-layout, index.json, blobs/sha256/*)
    by pulling all referenced blobs via the OrasClient and assembling them.
    Handles both single-platform manifests and multi-arch indexes.

    Args:
        image_ref: The image reference (e.g. 'nginx:latest'), used for logging.
        manifest: The OCI manifest dict (can be a single manifest or an index).
        oras_client: OrasClient instance to download blobs.
        output_tar_path: Path to write the output OCI layout tar.
        platforms: List of platforms to include (e.g. ['linux/amd64', 'linux/arm64']).
                  Empty or None means all platforms.
        pre_downloaded_blobs: Optional dict mapping blob digest → file path for blobs
                             already downloaded (e.g., from local daemon export).
                             These blobs are copied instead of downloaded from registry.

    Raises:
        ValueError: If the manifest structure is invalid or requested platform not found.
        OciRegistryError: If blob download or verification fails.
    """
    if platforms is None:
        platforms = []

    if pre_downloaded_blobs is None:
        pre_downloaded_blobs = {}

    # Apply platform filtering if requested
    manifest = _filter_manifests_by_platforms(manifest, platforms)
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

                if child_digest in pre_downloaded_blobs:
                    # Use pre-downloaded manifest
                    console.debug(f"Using pre-downloaded child manifest {child_digest}")
                    manifest_blob_path.write_bytes(Path(pre_downloaded_blobs[child_digest]).read_bytes())
                else:
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
                    pre_downloaded_blobs,
                )

            # Build index.json pointing to all child manifests with ref-name annotations
            # Preserve existing annotations while ensuring ref-name is present
            annotated_manifests = []
            for manifest_entry in manifests_list:
                annotated_entry = manifest_entry.copy()
                # Preserve existing annotations, add/update ref-name
                annotations = annotated_entry.get("annotations", {}).copy() if "annotations" in annotated_entry else {}
                annotations["org.opencontainers.image.ref.name"] = image_ref
                annotated_entry["annotations"] = annotations
                annotated_manifests.append(annotated_entry)

            index_json = {
                "schemaVersion": 2,
                "mediaType": media_type,
                "manifests": annotated_manifests,
            }
        else:
            # Single-platform manifest
            _download_manifest_blobs(manifest, oras_client, image_ref, blobs_dir, pre_downloaded_blobs)

            # Build index.json pointing to this single manifest
            manifest_digest = manifest.get("digest") or _compute_manifest_digest(manifest)
            # Size of the manifest serialized as JSON
            manifest_json_str = json_dumps(manifest, separators=(",", ":"), sort_keys=True)
            manifest_size = len(manifest_json_str.encode("utf-8"))

            # Write the manifest blob to blobs directory (required for valid OCI layout)
            manifest_blob_filename = manifest_digest.split(":")[-1]
            manifest_blob_path = blobs_dir / manifest_blob_filename
            manifest_blob_path.write_text(manifest_json_str)

            index_json = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": media_type,
                        "digest": manifest_digest,
                        "size": manifest_size,
                        "annotations": {
                            "org.opencontainers.image.ref.name": image_ref
                        },
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
    pre_downloaded_blobs: dict[str, str] | None = None,
) -> None:
    """Download config and layer blobs for a manifest.

    Args:
        manifest: The OCI manifest dict.
        oras_client: OrasClient instance.
        image_ref: Image reference for logging.
        blobs_dir: Directory to store blobs.
        pre_downloaded_blobs: Optional dict mapping digest → file path for blobs
                             already downloaded (e.g., from local daemon export).
                             These blobs are copied instead of downloaded.
    """
    if pre_downloaded_blobs is None:
        pre_downloaded_blobs = {}

    # Download config blob
    config = manifest.get("config", {})
    config_digest = config.get("digest", "")
    if config_digest:
        config_blob_filename = config_digest.split(":")[-1]
        config_blob_path = blobs_dir / config_blob_filename

        if config_digest in pre_downloaded_blobs:
            # Copy from pre-downloaded
            console.debug(f"Using pre-downloaded config blob {config_digest}")
            config_blob_path.write_bytes(Path(pre_downloaded_blobs[config_digest]).read_bytes())
        else:
            # Download from registry
            console.debug(f"Downloading config blob {config_digest}")
            oras_client.download_blob(image_ref, config_digest, str(config_blob_path))

        _verify_blob_digest(config_blob_path, config_digest)

    # Download layer blobs
    layers = manifest.get("layers", [])
    for layer in layers:
        layer_digest = layer.get("digest", "")
        if layer_digest:
            layer_blob_filename = layer_digest.split(":")[-1]
            layer_blob_path = blobs_dir / layer_blob_filename

            if layer_digest in pre_downloaded_blobs:
                # Copy from pre-downloaded
                console.debug(f"Using pre-downloaded layer blob {layer_digest}")
                layer_blob_path.write_bytes(Path(pre_downloaded_blobs[layer_digest]).read_bytes())
            else:
                # Download from registry
                console.debug(f"Downloading layer blob {layer_digest}")
                oras_client.download_blob(image_ref, layer_digest, str(layer_blob_path))


def _is_manifest_list_fully_resolved(
    manifest_list_exports: dict[str, str | None],
    requested_platforms: list[str] | None = None,
) -> bool:
    """Check if manifest list fully resolves all requested platforms.

    Args:
        manifest_list_exports: Dict from _resolve_all_platforms_from_manifest_list
                              mapping platform → export_tar (or None if unresolved).
        requested_platforms: List of requested platforms (or None/empty for all).

    Returns:
        True if all necessary platforms are fully resolved (non-None), False otherwise.
    """
    if not manifest_list_exports:
        return False

    # If no platform filter, all entries must be resolved
    if not requested_platforms:
        return all(export is not None for export in manifest_list_exports.values())

    # If filter is specified, all requested platforms must be resolved
    for platform in requested_platforms:
        if platform not in manifest_list_exports or manifest_list_exports[platform] is None:
            return False

    return True


def _assemble_multiplatform_from_manifest_list_exports(  # noqa: C901
    image_ref: str,
    manifest_list_exports: dict[str, str | None],
    output_tar_path: str,
    daemon_export_dir: str,
) -> None:
    """Assemble a multi-platform OCI layout from locally-exported daemon tars.

    Takes a dict of platform → export_tar mappings (where export_tar is a path to
    an OCI-archive tar from _resolve_all_platforms_from_manifest_list or daemon export),
    extracts all blobs from those tars, and assembles them into a single OCI image layout
    tar at output_tar_path.

    This is used when a manifest list fully resolves locally, so we can assemble
    the output without any registry contact.

    Args:
        image_ref: Image reference (for logging).
        manifest_list_exports: Dict mapping platform → export_tar path (or None).
        output_tar_path: Path to write the final assembled OCI layout tar.
        daemon_export_dir: Temporary directory for intermediate blob storage.

    Raises:
        OciRegistryError: If assembly fails.
    """
    pre_downloaded_blobs: dict[str, str] = {}
    persistent_blob_dir = Path(daemon_export_dir) / "blobs_cache"

    # Extract blobs from all exported tars
    for platform_str, export_tar in manifest_list_exports.items():
        if export_tar is None:
            continue  # Skip unresolved platforms
        console.debug(f"Extracting blobs from {platform_str} export: {export_tar}")
        _extract_blobs_from_daemon_tar(export_tar, platform_str, pre_downloaded_blobs, persistent_blob_dir)

    # Build a synthetic index.json that will be used by _create_oci_image_layout_tar
    # Since we're assembling from local daemon exports, we need to construct the manifest/index
    # that ties them together
    synth_index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [],
    }

    # For each successfully resolved platform, add a manifest entry
    # (we'll construct minimal entries; the full manifest blobs are in pre_downloaded_blobs)
    for platform_str, export_tar in manifest_list_exports.items():
        if export_tar is None:
            continue

        # Extract the platform descriptor from the platform string
        # e.g. "linux/amd64" → {"os": "linux", "architecture": "amd64"}
        parts = platform_str.split("/")
        if len(parts) >= 2:  # noqa: PLR2004
            platform_dict = {
                "os": parts[0],
                "architecture": parts[1],
            }
            if len(parts) > 2:  # noqa: PLR2004
                platform_dict["variant"] = parts[2]

            # Extract the manifest digest from the daemon export tar (it's in index.json)
            temp_dir = Path(mkdtemp())
            try:
                with tar_open(export_tar, "r") as tar:
                    tar.extractall(temp_dir, filter="data")

                # Read index.json from the daemon export
                index_path = temp_dir / "index.json"
                if index_path.exists():
                    with index_path.open() as f:
                        daemon_index = json_load(f)

                    # Get the manifest descriptor from the daemon export
                    manifests = daemon_index.get("manifests", [])
                    if manifests:
                        manifest_desc = manifests[0].copy()
                        manifest_desc["platform"] = platform_dict
                        # Ensure ref-name annotation
                        if "annotations" not in manifest_desc:
                            manifest_desc["annotations"] = {}
                        manifest_desc["annotations"]["org.opencontainers.image.ref.name"] = image_ref
                        synth_index["manifests"].append(manifest_desc)
            finally:
                rmtree(temp_dir, ignore_errors=True)

    # Now assemble using _create_oci_image_layout_tar with the synthetic index
    # Create a minimal OrasClient mock for this call (only used for blob downloads, which we skip)
    class _NoOpOrasClient:
        def download_blob(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
            """No-op: blobs already present in pre_downloaded_blobs."""

    _create_oci_image_layout_tar(
        image_ref,
        synth_index,
        _NoOpOrasClient(),  # type: ignore[arg-type]
        output_tar_path,
        [],
        pre_downloaded_blobs,
    )

    console.debug(f"Assembled multi-platform OCI layout from manifest-list exports: {output_tar_path}")


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


def package(  # noqa: PLR0913
    package_type: PackageType,
    *,
    project_dir: str = ".",
    build_dir: str = ".dist",
    output: str | None = None,
    include_images: bool = True,
    runtime: str = "auto",
    platforms: list[str] | None = None,
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
        output: Override output DIRECTORY for the bundle (default: .dist/<version>/).
               The bundle filename is always <id>-<version>.tgz and is not overridable.
        include_images: Whether to discover and bundle referenced container images
                       (default True). Set to False to restore Item 2's pure-local
                       no-network behavior.
        runtime: Container daemon lookup strategy: 'auto' (default, probe Podman → Docker),
                'podman' (Podman only), 'docker' (Docker only), or 'none' (registry-only).
                Only meaningful when include_images=True.
        platforms: List of platforms to include (e.g. ['linux/amd64', 'linux/arm64']).
                  Empty or None means all platforms. Only applies to image inclusion.

    Returns:
        Path to the created bundle .tgz file.

    Raises:
        ValueError: If build output missing, requested types undefined, collision detected,
                   or --runtime and --no-images both specified.
    """
    # Validate mutual exclusion of runtime and include_images
    if not include_images and runtime != "auto":
        msg = "--runtime and --no-images are mutually exclusive"
        raise ValueError(msg)
    # Validate platform + no_images exclusion
    _validate_platform_no_images_exclusion(platforms, not include_images)

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
        runtime=runtime,
        platforms=platforms or [],
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
    runtime: str = "auto",
    platforms: list[str] | None = None,
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
        output_override: Override output DIRECTORY (or None for default .dist/<version>/).
                        The bundle filename is always <id>-<version>.tgz and is not overridable.
        include_images: Whether to discover and include container images (default True).
        runtime: Container daemon lookup strategy: 'auto' (default, probe Podman → Docker),
                'podman' (Podman only), 'docker' (Docker only), or 'none' (registry-only).
                Only meaningful when include_images=True.
        platforms: List of platforms to include (e.g. ['linux/amd64', 'linux/arm64']).
                  Empty or None means all platforms.

    Returns:
        Path to created bundle .tgz file.

    Raises:
        CredentialsExpiredError: If a registry credential has expired.
        OciRegistryError: If pulling an image fails.
    """
    if platforms is None:
        platforms = []
    margo_build_path = Path(build_dir) / margo_version
    root_dir_name = f"{meta.id}-{margo_version}"

    # Determine output directory and enforce bundle filename
    output_dir = Path(output_override) if output_override else margo_build_path
    bundle_path = output_dir / f"{meta.id}-{margo_version}.tgz"

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

        # 3. Discover and include container images if requested
        if include_images:
            try:
                _discover_and_include_images(
                    staging_root,
                    types_to_include,
                    build_dir,
                    meta,
                    component_versions,
                    runtime,
                    platforms=platforms,
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


def _discover_and_include_images(  # noqa: C901, PLR0912, PLR0913, PLR0915
    staging_root: Path,
    types_to_include: set[PackageType],
    build_dir: str,
    meta: MargoYaml,
    component_versions: dict[PackageType, list[str]],
    runtime: str,
    platforms: list[str] | None = None,
) -> None:
    """Discover container images from compose/quadlet and include them in the bundle.

    Scans all built component content to discover image references, regardless of any
    image: configuration in margo.yaml. This ensures every referenced image (including
    base/third-party images) is pulled and included in the bundle for offline deployment.

    Reads built component archives, discovers image references, validates them,
    attempts pulls via local daemon lookup (if enabled) then registry fallback,
    and saves each as an OCI image-layout tar under images/ folder.

    Args:
        staging_root: Root of the bundle staging directory.
        types_to_include: Component types to process.
        build_dir: Build output directory.
        meta: Loaded margo.yaml.
        component_versions: Map of component type to list of versions.
        runtime: Container daemon lookup strategy.
        platforms: List of platforms to include (e.g. ['linux/amd64', 'linux/arm64']).
                  Empty or None means all platforms.

    Raises:
        OciRegistryError: If pulling an image fails.
    """
    if platforms is None:
        platforms = []

    # VALIDATION: Validate all --platform values up front, before any I/O
    # This ensures invalid values (e.g. "all") fail fast regardless of runtime mode
    for platform in platforms:
        try:
            _validate_platform(platform)
        except ValueError as e:
            msg = f"Invalid --platform value: {e}"
            console.fatal(msg)
            raise OciRegistryError(msg) from e

    images_dir = staging_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    discovered_refs = set()  # Track unique refs to avoid duplicate pulls

    # Discover images from compose components (scan all built content regardless of image: config)
    if PackageType.COMPOSE in types_to_include and meta.compose is not None:
        for comp_version in component_versions.get(PackageType.COMPOSE, []):
            version_path = Path(build_dir) / comp_version
            for tgz in version_path.glob(f"{meta.name}-*.tgz"):
                console.debug(f"Discovering compose images in {tgz.name}")
                refs = _discover_image_references_compose(str(tgz))
                for ref in refs:
                    if ref not in discovered_refs:
                        discovered_refs.add(ref)
                        console.info(f"Found image reference: {ref}")

    # Discover images from quadlet components (scan all built content regardless of image: config)
    if PackageType.QUADLET in types_to_include and meta.quadlet is not None:
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
        console.debug("No image references found in components")
        return

    # Initialize OrasClients per registry (lazy; credentials are best-effort)
    registry_clients: dict[str, OrasClient] = {}

    # Pull and materialize each image
    pulled_images: dict[str, str] = {}  # Track ref -> tar_path for deduplication
    failed_pulls: list[tuple[str, Exception]] = []

    # Create a temporary directory for daemon exports
    daemon_export_dir = Path(mkdtemp(prefix="margot-daemon-"))

    for ref in discovered_refs:
        if ref in pulled_images:
            # Already pulled this exact ref (deduplicated)
            continue

        # Create a safe deterministic filename from the image ref
        # nginx:latest -> nginx_latest.tar
        # public.ecr.aws/org/repo:1.0 -> public_ecr_aws_org_repo_1_0.tar
        safe_filename = ref.replace("/", "_").replace(":", "_").replace(".", "_") + ".tar"
        image_tar_path = images_dir / safe_filename

        try:
            console.info(f"Pulling image: {ref}")

            # Validate the reference
            try:
                validate_uri(ref)
            except ValueError as e:
                msg = f"Invalid image reference: {ref}: {e}"
                raise OciRegistryError(msg) from e

            # Extract hostname for registry operations
            try:
                hostname = extract_hostname(ref)
            except ValueError as e:
                msg = f"Cannot extract hostname from image reference {ref}: {e}"
                raise OciRegistryError(msg) from e

            # Initialize OrasClient for this registry if not already done (for registry pulls)
            # Credentials are best-effort: attempt anonymous pull if no credential stored
            if hostname not in registry_clients:
                console.debug(f"Initializing OrasClient for {hostname}")
                try:
                    # Check if credential exists and is not expired
                    check_credentials(hostname)
                except CredentialsExpiredError:
                    # Expired credential is an error; add to failed_pulls for aggregate reporting
                    raise
                except Exception:  # noqa: BLE001
                    # Any other credential check error (e.g., no credential) is best-effort
                    # and will attempt anonymous pull
                    console.debug(f"No stored credential for {hostname}; will attempt anonymous pull")

                registry_clients[hostname] = OrasClient(hostname=hostname)

            # Branch behavior based on runtime mode
            if runtime in (RuntimeLookup.PODMAN.value, RuntimeLookup.DOCKER.value):
                # FORCED DAEMON MODE: daemon is the sole authority, NO registry contact
                daemon_tar = _lookup_image_with_runtime(
                    ref,
                    str(daemon_export_dir),
                    runtime,
                    registry_clients.get(hostname) or OrasClient(),
                )
                if daemon_tar is None:
                    # Daemon lookup already raises RuntimeError if required=True and daemon unreachable
                    msg = f"Image {ref} not found in {runtime} daemon"
                    raise_msg = OciRegistryError(msg)
                    raise raise_msg from None  # noqa: TRY301

                # Daemon was the source; check platform filter against daemon's reported platform
                # For now, assume the daemon export is valid and use it as-is
                # TODO(kiro): If --platform is specified and doesn't match daemon's platform,
                # should fail with clear error. Currently we accept daemon's platform as-is.
                image_tar_path.write_bytes(Path(daemon_tar).read_bytes())
                console.info(f"Used local {runtime} daemon image: {ref} → {safe_filename}")
                pulled_images[ref] = str(image_tar_path)

            elif runtime == RuntimeLookup.NONE.value:
                # REGISTRY-ONLY MODE: skip daemon lookup entirely
                oras_client = registry_clients[hostname]

                # Get the manifest (handles both single-arch and multi-arch)
                try:
                    manifest = oras_client.get_manifest(ref)
                except Exception as e:
                    msg = (
                        f"Registry did not return a valid manifest for {ref} — the image "
                        f"may not exist at this reference, or the registry may be unreachable: {e}"
                    )
                    raise OciRegistryError(msg) from e

                # Create OCI image layout tar with all blobs (respecting --platform filter)
                _create_oci_image_layout_tar(ref, manifest, oras_client, str(image_tar_path), platforms)

                console.info(f"Pulled and materialized: {ref} → {safe_filename}")
                pulled_images[ref] = str(image_tar_path)

            else:
                # AUTO MODE: registry is authoritative for platform set, daemon used opportunistically
                # Manifest-list resolution is checked FIRST before registry contact.

                oras_client = registry_clients[hostname]
                daemon_export_temp = Path(daemon_export_dir)
                daemon_export_temp.mkdir(parents=True, exist_ok=True)

                # PRIORITY 1: Check local Podman manifest list FIRST (skip registry entirely if fully resolved)
                console.debug(f"Checking for local Podman manifest list for {ref}")
                manifest_list_exports = _resolve_all_platforms_from_manifest_list(ref, str(daemon_export_temp))

                # Check if manifest list fully resolves all requested platforms (or all platforms if no filter)
                if manifest_list_exports and _is_manifest_list_fully_resolved(
                    manifest_list_exports, platforms
                ):
                    # Manifest list fully resolves all needed platforms — skip registry contact entirely
                    console.info(
                        f"Local manifest list fully resolves {ref}, skipping registry contact"
                    )
                    _assemble_multiplatform_from_manifest_list_exports(
                        ref,
                        manifest_list_exports,
                        str(image_tar_path),
                        str(daemon_export_dir),
                    )
                    console.info(f"Pulled and materialized: {ref} → {safe_filename}")
                    pulled_images[ref] = str(image_tar_path)
                    continue  # Skip to next ref; no registry contact needed

                # PRIORITY 2: Registry is the source of truth for platform set
                try:
                    registry_manifest = oras_client.get_manifest(ref)
                except Exception as e:
                    # Registry unreachable; try degraded fallback: manifest-list-aware resolution
                    console.debug(f"Registry unreachable for {ref}: {e}, trying degraded fallback...")

                    # Re-check manifest list if not already done above
                    if not manifest_list_exports:
                        manifest_list_exports = _resolve_all_platforms_from_manifest_list(
                            ref, str(daemon_export_temp)
                        )

                    if manifest_list_exports:
                        # Manifest list exists and resolved some (or all) platforms
                        resolved_platforms = [p for p, export in manifest_list_exports.items() if export is not None]
                        if resolved_platforms:
                            # We have at least some platforms from the manifest list
                            console.warning(
                                f"Registry unreachable for {ref}; using {len(resolved_platforms)} platform(s) "
                                f"from local manifest list: {', '.join(resolved_platforms)}. "
                                f"For full multi-platform support, ensure registry access. → {safe_filename}"
                            )
                            _assemble_multiplatform_from_manifest_list_exports(
                                ref,
                                manifest_list_exports,
                                str(image_tar_path),
                                str(daemon_export_dir),
                            )
                            pulled_images[ref] = str(image_tar_path)
                            continue  # Skip to next ref; don't fail

                    # Fallback: try single platform from daemon (old behavior)
                    console.debug("Manifest list unavailable or unresolved, trying single daemon image...")
                    daemon_tar = _lookup_image_with_runtime(
                        ref,
                        str(daemon_export_dir),
                        "auto",
                        oras_client,
                    )
                    if daemon_tar:
                        # Degraded mode: single platform from daemon with explicit warning
                        image_tar_path.write_bytes(Path(daemon_tar).read_bytes())
                        console.warning(
                            f"Registry unreachable and manifest list not available for {ref}; "
                            f"using local daemon copy (single platform only). "
                            f"For full multi-platform support, ensure registry access. → {safe_filename}"
                        )
                        pulled_images[ref] = str(image_tar_path)
                        continue  # Skip to next ref; don't fail

                    # Neither registry nor daemon available
                    msg = (
                        f"Registry unreachable for {ref} and no local daemon copy available. "
                        f"Cannot proceed: {e}"
                    )
                    raise OciRegistryError(msg) from e

                # Step 2: Determine target platform set (full registry index, or --platform-filtered)
                # This validates --platform values too (via _filter_manifests_by_platforms)
                target_manifest = registry_manifest
                if platforms:
                    target_manifest = _filter_manifests_by_platforms(registry_manifest, platforms)

                # Step 3: For each target platform, check local daemons (Podman → Docker)
                # then download from registry as needed
                _pull_image_with_local_daemon_optimization(
                    ref,
                    target_manifest,
                    oras_client,
                    str(image_tar_path),
                    str(daemon_export_dir),
                )

                console.info(f"Pulled and materialized: {ref} → {safe_filename}")
                pulled_images[ref] = str(image_tar_path)

        except (OciRegistryError, CredentialsExpiredError) as e:
            console.warning(f"Failed to pull image {ref}: {e}")
            failed_pulls.append((ref, e))
        except Exception as e:  # noqa: BLE001
            console.warning(f"Unexpected error pulling image {ref}: {e}")
            failed_pulls.append((ref, e))

    # Clean up daemon export directory
    with contextlib.suppress(Exception):
        rmtree(daemon_export_dir, ignore_errors=True)

    # If any pulls failed, abort the entire package operation
    if failed_pulls:
        msg = f"Failed to pull {len(failed_pulls)} image(s): "
        refs_str = ", ".join(ref for ref, _ in failed_pulls)
        console.fatal(f"{msg}{refs_str}")
        raise OciRegistryError(msg + refs_str)

    console.info(f"Successfully pulled and materialized {len(pulled_images)} unique image(s)")


def _pull_image_with_local_daemon_optimization(
    image_ref: str,
    target_manifest: dict[str, Any],
    oras_client: OrasClient,
    output_tar_path: str,
    daemon_export_dir: str,
) -> None:
    """Pull an image in auto mode, using local daemon for matching platforms when available.

    In auto mode, the registry manifest/index is authoritative for the platform set.
    Local sources are checked in priority order:
    1. Local Podman manifest list (if present) — ALL resolvable child platforms exported locally
    2. Per-platform daemon lookup (Podman → Docker) for platforms not resolved via manifest list
    3. Registry fallback for any remaining platforms

    This optimizes bandwidth/time for local hits while ensuring all requested platforms
    are included from the registry as a fallback.

    Args:
        image_ref: Image reference (e.g. 'nginx:latest').
        target_manifest: The OCI manifest/index to pull (already registry-fetched and possibly filtered).
        oras_client: OrasClient instance for registry pulls.
        output_tar_path: Path to write the final OCI layout tar.
        daemon_export_dir: Temporary directory for daemon exports.

    Raises:
        OciRegistryError: If pulling or assembly fails.
    """
    # Determine the list of platform slots to fill from the manifest
    media_type = target_manifest.get("mediaType", "")
    is_index = "index" in media_type

    platform_slots: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    if is_index:
        # Multi-platform index: each entry in manifests is a platform slot
        manifests_list = target_manifest.get("manifests", [])
        for manifest_entry in manifests_list:
            platform_desc = manifest_entry.get("platform")
            platform_slots.append((manifest_entry, platform_desc))
    else:
        # Single-platform manifest: one implicit slot
        platform_slots.append((target_manifest, None))

    # For each platform slot, try local sources first, then fall back to registry
    pre_downloaded_blobs: dict[str, str] = {}
    daemon_export_temp = Path(daemon_export_dir)
    daemon_export_temp.mkdir(parents=True, exist_ok=True)

    # STEP 1: Check for local Podman manifest list — highest priority (all platforms at once)
    console.debug(f"Checking for local Podman manifest list for {image_ref}")
    manifest_list_exports = _resolve_all_platforms_from_manifest_list(image_ref, str(daemon_export_temp))

    # Track which platforms were resolved via manifest list
    manifest_list_platforms = set()

    for platform_str, export_tar in manifest_list_exports.items():
        if export_tar is not None:
            console.debug(f"Using manifest-list resolution for {platform_str}: {export_tar}")
            persistent_blobs_dir = Path(daemon_export_dir) / "blobs_cache"
            _extract_blobs_from_daemon_tar(export_tar, platform_str, pre_downloaded_blobs, persistent_blobs_dir)
            manifest_list_platforms.add(platform_str)
        else:
            console.debug(f"Manifest list entry exists for {platform_str} but digest did not resolve locally")

    # STEP 2: For remaining platforms (not resolved via manifest list), try per-platform daemon lookup
    for _slot_manifest_descriptor, platform_desc in platform_slots:
        platform_str = _platform_descriptor_to_string(platform_desc)

        # Skip if already resolved via manifest list
        if platform_str in manifest_list_platforms:
            console.debug(f"Platform {platform_str} already resolved via manifest list, skipping daemon lookup")
            continue

        console.debug(f"Processing platform slot: {platform_str} (no manifest-list match)")

        # Try to find a matching local daemon image
        daemon_tar = _try_daemon_match_for_platform(
            image_ref, platform_str, platform_desc, daemon_export_temp
        )

        if daemon_tar:
            # Extract blobs from daemon tar and collect digests for later assembly
            console.debug(f"Using daemon export for {platform_str}: {daemon_tar}")
            persistent_blobs_dir = Path(daemon_export_dir) / "blobs_cache"
            _extract_blobs_from_daemon_tar(daemon_tar, platform_str, pre_downloaded_blobs, persistent_blobs_dir)
        else:
            console.debug(f"No local daemon match for {platform_str}, will pull from registry")

    # STEP 3: Assemble the final OCI layout, using pre-downloaded blobs where available
    # Registry pull will happen for any platforms not covered by manifest list or daemon
    _create_oci_image_layout_tar(
        image_ref, target_manifest, oras_client, output_tar_path, [], pre_downloaded_blobs
    )



def _platform_descriptor_to_string(platform_desc: dict[str, Any] | None) -> str:
    """Convert an OCI platform descriptor to a platform string.

    Args:
        platform_desc: Platform descriptor dict with 'os', 'architecture', optionally 'variant'.
                      None means unknown/single-platform.

    Returns:
        Platform string (e.g. 'linux/amd64') or 'unknown' if None.
    """
    if not platform_desc:
        return "unknown"

    os_part = platform_desc.get("os", "unknown")
    arch_part = platform_desc.get("architecture", "unknown")
    variant_part = platform_desc.get("variant")

    if variant_part:
        return f"{os_part}/{arch_part}/{variant_part}"
    return f"{os_part}/{arch_part}"


def _try_daemon_match_for_platform(
    image_ref: str,
    platform_str: str,
    platform_desc: dict[str, Any] | None,
    export_dir: Path,
) -> str | None:
    """Try to find and export a matching local daemon image for a platform.

    Tries Podman then Docker (auto-probe order). Returns path to exported tar if found.

    Args:
        image_ref: Image reference.
        platform_str: Platform string (e.g. 'linux/amd64').
        platform_desc: OCI platform descriptor dict (for matching).
        export_dir: Directory to write exported tar.

    Returns:
        Path to exported OCI-archive tar, or None if no match found.
    """
    # Try Podman first
    podman_export = _lookup_image_podman(image_ref, str(export_dir), required=False)
    if podman_export and _verify_daemon_export_platform_match(podman_export, platform_str, platform_desc):
        return podman_export

    # Try Docker as fallback
    docker_export = _lookup_image_docker(image_ref, str(export_dir), required=False)
    if docker_export and _verify_daemon_export_platform_match(docker_export, platform_str, platform_desc):
        return docker_export

    return None


def _verify_daemon_export_platform_match(
    export_tar: str,
    platform_str: str,
    platform_desc: dict[str, Any] | None,
) -> bool:
    """Verify that a daemon-exported tar's platform matches the requested one.

    Args:
        export_tar: Path to daemon export tar.
        platform_str: Requested platform string.
        platform_desc: OCI platform descriptor to match against.

    Returns:
        True if platform matches, False otherwise.
    """
    if not platform_desc:
        # Single-platform manifest: accept the match
        return True

    # Extract the manifest from the OCI-archive and check its platform
    temp_dir = Path(mkdtemp())
    try:
        with tar_open(export_tar, "r") as tar:
            tar.extractall(temp_dir, filter="data")

        # OCI-archive stores the manifest in index.json or as a single manifest
        index_json_path = temp_dir / "index.json"
        if index_json_path.exists():
            with index_json_path.open() as f:
                index_data = json_load(f)

            # Check if this is an index or single manifest
            media_type = index_data.get("mediaType", "")
            if "index" in media_type:
                # It's an index; we might need the first entry
                manifests = index_data.get("manifests", [])
                if manifests:
                    exported_platform = manifests[0].get("platform")
                else:
                    return False
            else:
                # Single manifest in index.json entry
                # The platform info is stored in the manifest entry's annotations/platform
                manifests = index_data.get("manifests", [])
                if manifests:
                    exported_platform = manifests[0].get("platform")
                else:
                    return False
        else:
            # Fallback: no index.json, can't verify platform
            return False

        # Use _platform_matches_manifest to verify
        return _platform_matches_manifest(platform_str, exported_platform)

    except Exception as e:  # noqa: BLE001
        console.debug(f"Failed to verify daemon export platform: {e}")
        return False
    finally:
        rmtree(temp_dir, ignore_errors=True)


def _extract_blobs_from_daemon_tar(
    daemon_tar: str,
    platform_str: str,
    pre_downloaded_blobs: dict[str, str],
    persistent_blob_dir: Path,
) -> None:
    """Extract blobs from a daemon export tar and record them for later assembly.

    Copies blobs to persistent_blob_dir so they survive temp cleanup.

    Args:
        daemon_tar: Path to daemon export tar (OCI-archive format).
        platform_str: Platform string (for logging).
        pre_downloaded_blobs: Dict to update with digest → blob_path mappings.
        persistent_blob_dir: Directory to persistently store copied blobs.
    """
    temp_dir = Path(mkdtemp())
    try:
        with tar_open(daemon_tar, "r") as tar:
            tar.extractall(temp_dir, filter="data")

        # Copy all blobs from the daemon export to the persistent directory
        blobs_source_dir = temp_dir / "blobs" / "sha256"
        if blobs_source_dir.exists():
            persistent_blob_dir.mkdir(parents=True, exist_ok=True)
            for blob_file in blobs_source_dir.iterdir():
                if blob_file.is_file():
                    # Copy blob to persistent location
                    digest = f"sha256:{blob_file.name}"
                    persistent_blob_path = persistent_blob_dir / blob_file.name
                    persistent_blob_path.write_bytes(blob_file.read_bytes())
                    # Record the persistent path in pre_downloaded_blobs
                    pre_downloaded_blobs[digest] = str(persistent_blob_path)
                    console.debug(f"Recorded blob {digest} from daemon export ({platform_str})")

    except Exception as e:  # noqa: BLE001
        console.debug(f"Failed to extract blobs from daemon tar: {e}")
    finally:
        rmtree(temp_dir, ignore_errors=True)


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
