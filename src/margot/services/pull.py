"""Pull service: orchestrate OCI artifact retrieval to disk."""

from pathlib import Path
from typing import Any

from margot.domain import uri as uri_domain
from margot.domain.layers import COMPOSE_LAYER_MEDIA_TYPE, QUADLET_LAYER_MEDIA_TYPE, resolve_filename, select_payload_layer
from margot.domain.models import PackageType, artifact_type_to_package_type
from margot.infra import oci

_PAYLOAD_MEDIA_TYPES: dict[PackageType, str] = {
    PackageType.COMPOSE: COMPOSE_LAYER_MEDIA_TYPE,
    PackageType.QUADLET: QUADLET_LAYER_MEDIA_TYPE,
}


def pull_artifact(uri: str, outdir: str = ".") -> list[str]:
    """
    Pull OCI artifact layers to outdir.

    Steps:
    1. Validate URI (via domain/uri.py).
    2. Fetch manifest.
    3. Detect artifact type via the artifactType field.
    4. Pull layers to outdir.
    5. For compose/quadlet: rename the payload file if a better name can be resolved.
    6. Return list of written file paths.

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0).
        outdir: Destination directory (created if needed).

    Returns:
        List of paths to written files.

    Raises:
        ValueError: If URI is malformed.
        Exception: If pull or manifest fetch fails.
    """
    uri_domain.validate_uri(uri)

    Path(outdir).mkdir(parents=True, exist_ok=True)

    client = oci.OrasClient()
    manifest: dict[str, Any] = client.get_manifest(uri)

    artifact_type: str | None = manifest.get("artifactType")
    package_type = artifact_type_to_package_type(artifact_type)

    pulled_paths: list[str] = client.pull(uri=uri, outdir=outdir)

    if not pulled_paths:
        return []

    if package_type in _PAYLOAD_MEDIA_TYPES:
        pulled_paths = _apply_payload_naming(
            pulled_paths=pulled_paths,
            manifest=manifest,
            package_type=package_type,
            outdir=outdir,
        )

    return pulled_paths


def _apply_payload_naming(
    pulled_paths: list[str],
    manifest: dict[str, Any],
    package_type: PackageType,
    outdir: str,
) -> list[str]:
    """Rename the compose/quadlet payload file if a better name is available.

    Args:
        pulled_paths: List of file paths returned by oras pull.
        manifest: The OCI manifest dict.
        package_type: Detected PackageType (COMPOSE or QUADLET).
        outdir: The directory where files were written.

    Returns:
        Updated list of file paths (with any rename applied).
    """
    media_type = _PAYLOAD_MEDIA_TYPES[package_type]
    layers: list[dict[str, Any]] = manifest.get("layers") or []
    payload_layer = select_payload_layer(layers, media_type)

    if payload_layer is None:
        return pulled_paths

    manifest_annotations: dict[str, Any] | None = manifest.get("annotations")
    desired_name = resolve_filename(payload_layer, manifest_annotations)

    if desired_name is None:
        return pulled_paths

    outdir_path = Path(outdir)
    updated_paths: list[str] = []

    for path_str in pulled_paths:
        current_path = Path(path_str)
        if current_path.name != desired_name and current_path.parent == outdir_path:
            new_path = outdir_path / desired_name
            current_path.rename(new_path)
            updated_paths.append(str(new_path))
        else:
            updated_paths.append(path_str)

    return updated_paths
