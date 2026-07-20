"""Pull service: orchestrate OCI artifact retrieval to disk."""

from pathlib import Path
from typing import Any

import margot.console as console
from margot.domain import uri as uri_domain
from margot.domain.layers import COMPOSE_LAYER_MEDIA_TYPE, QUADLET_LAYER_MEDIA_TYPE, resolve_filename
from margot.domain.models import (
    _ARTIFACT_TYPE_MAP,
    PackageType,
    artifact_type_to_package_type,
)
from margot.domain.uri import extract_tag, validate_semver_tag
from margot.infra import oci

_PAYLOAD_MEDIA_TYPES: dict[PackageType, str] = {
    PackageType.COMPOSE: COMPOSE_LAYER_MEDIA_TYPE,
    PackageType.QUADLET: QUADLET_LAYER_MEDIA_TYPE,
}

_MEDIA_TYPE_NAMES: dict[str, str] = {v: k.name.lower() for k, v in _PAYLOAD_MEDIA_TYPES.items()}


def _available_layer_types(layers: list[dict]) -> str:
    """
    Build a human-readable string listing the mediaTypes found in layers.

    Each known type is shown with its friendly name; unknown types are
    shown as their raw mediaType string.

    Args:
        layers: List of OCI layer descriptors from a manifest.

    Returns:
        A string like:
        'Available layer types: quadlet (application/vnd.org.margo.component.quadlet.tar+gzip)'
        or 'No layers present.' if the list is empty.
    """
    if not layers:
        return "No layers present."
    parts: list[str] = []
    for layer in layers:
        mt = layer.get("mediaType", "")
        name = _MEDIA_TYPE_NAMES.get(mt)
        if name:
            parts.append(f"{name} ({mt})")
        else:
            parts.append(mt)
    return "Available layer types: " + ", ".join(parts)


def pull_artifact(
    uri: str,
    outdir: str = ".",
    *,
    force: bool = False,
    force_type: PackageType | None = None,
) -> list[str]:
    """
    Pull OCI artifact layers to outdir.

    For compose/quadlet artifacts: downloads matching layers individually, resolves filenames.
    For other types (margo, unknown): delegates to client.pull() for bulk download.

    Steps:
    1. Validate URI (via domain/uri.py).
    2. Guard: force_type requires force.
    3. SemVer gate: reject non-SemVer tags unless force=True.
    4. Create outdir.
    5. Fetch manifest.
    6. Detect artifact type via the artifactType field; override with force_type if set.
    7. If package_type not in _PAYLOAD_MEDIA_TYPES: use client.pull() (margo, unknown types).
    8. Otherwise: own the layer loop.
       a. Get target mediaType for this package_type.
       b. Filter manifest layers by that mediaType.
       c. Hard-fail if no matching layers found.
       d. For each layer: resolve filename and download individually.
    9. Return list of written file paths.

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0).
        outdir: Destination directory (created if needed).
        force: Bypass SemVer gate and malicious annotation checks.
        force_type: Override detected artifact type interpretation.

    Returns:
        List of paths to written files.

    Raises:
        ValueError: If URI is malformed.
        ValueError: If tag is not valid SemVer and force=False.
        ValueError: If compose/quadlet artifact has no matching layers.
        ValueError: If artifact type is unknown and force=False.
        Exception: If pull or manifest fetch fails.
    """
    uri_domain.validate_uri(uri)
    console.info(f"URI validated: {uri}")

    tag = extract_tag(uri)
    if not validate_semver_tag(tag) and not force:
        raise ValueError(f"Tag '{tag}' is not valid SemVer. Use --force to pull anyway.")
    console.info(f"Tag '{tag}' is valid SemVer.")

    Path(outdir).mkdir(parents=True, exist_ok=True)
    console.info(f"Output directory ready: {outdir}")

    client = oci.OrasClient()
    manifest: dict[str, Any] = client.get_manifest(uri)
    console.info("Manifest fetched.")

    artifact_type: str | None = manifest.get("artifactType")
    package_type = artifact_type_to_package_type(artifact_type)
    console.info(f"Detected artifact type: {package_type.value if package_type else 'unknown'}")

    if force_type is not None:
        package_type = force_type
        console.info(f"Artifact type overridden to: {force_type.value}")

    # Step 7: Handle UNKNOWN type or known types
    if package_type == PackageType.UNKNOWN:
        if not force:
            artifact_type_str = manifest.get("artifactType") or "(none)"
            supported = ", ".join(sorted(_ARTIFACT_TYPE_MAP.keys()))
            raise ValueError(
                f"Unknown artifact type: '{artifact_type_str}'. Supported types: {supported}. Use --force to attempt pull anyway."
            )
        # force=True: fall through to client.pull(), result may be empty
        pulled_paths: list[str] = client.pull(uri=uri, outdir=outdir)
        console.info(f"Pulled {len(pulled_paths)} layer(s).")
        return pulled_paths or []

    if package_type == PackageType.MARGO:
        pulled_paths = client.pull(uri=uri, outdir=outdir)
        console.info(f"Pulled {len(pulled_paths)} layer(s).")
        return pulled_paths or []

    # Step 8: Own the layer loop for compose/quadlet
    target_media_type = _PAYLOAD_MEDIA_TYPES[package_type]
    layers: list[dict[str, Any]] = manifest.get("layers") or []
    matching_layers = [layer for layer in layers if layer.get("mediaType") == target_media_type]

    if not matching_layers:
        available = _available_layer_types(layers)
        raise ValueError(f"No layer with mediaType '{target_media_type}' found.\n{available}")

    result: list[str] = []
    manifest_annotations: dict[str, Any] | None = manifest.get("annotations")

    for layer in matching_layers:
        # Resolve desired filename
        desired_name = resolve_filename(layer, manifest_annotations, force=force)

        # Fall back to digest-based name if no name resolved
        if desired_name is None:
            digest_hex = layer["digest"].split(":", 1)[-1][:12]
            desired_name = digest_hex
        else:
            console.info(f"Layer filename resolved: {desired_name}.")

        outfile = str(Path(outdir) / desired_name)
        client.download_blob(uri, layer["digest"], outfile)
        result.append(outfile)

    console.info(f"Pulled {len(result)} layer(s).")
    return result
