"""Remote OCI artifact resolver: pull and inspect remote Margo application descriptors.

This service handles the complete lifecycle of remote descriptor resolution:
- Shared OCI preparation (URI normalization, validation, credential check, manifest fetch)
- Margo-only gating (compose/quadlet/unknown fail before pull)
- Pulling to a temporary directory (recursive=False)
- Root app.yaml location and validation
- Temporary directory cleanup responsibility (caller's finally block)

No Rich rendering or terminal output — pure data and exceptions.
"""

from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Any

from margot import console
from margot.domain.layers import MARGO_DESCRIPTION_MEDIA_TYPE
from margot.domain.models import PackageType
from margot.services import pull as pull_service


@dataclass(frozen=True)
class ResolvedRemoteDescriptor:
    """A remote Margo application descriptor ready for use.

    Attributes:
        normalized_uri: The OCI reference in canonical form (no oci:// scheme).
        app_yaml_path: Absolute filesystem path to the pulled app.yaml.
        temp_dir: Live TemporaryDirectory handle whose cleanup is the caller's responsibility.
    """

    normalized_uri: str
    app_yaml_path: str
    temp_dir: TemporaryDirectory


def resolve_remote_descriptor(uri: str) -> ResolvedRemoteDescriptor:
    """Resolve a remote Margo application descriptor and pull it to a temporary directory.

    Uses the shared prepare_oci_retrieval from services/pull to centralize URI validation,
    credential checks, and manifest fetching. Verifies that the artifact is a Margo
    application descriptor (rejects compose/quadlet/unknown), pulls the artifact
    with recursive=False, and locates the descriptor layer by mediaType. The temporary
    directory remains live; cleanup is the caller's responsibility.

    Args:
        uri: Full OCI reference, optionally with 'oci://' scheme prefix.
            Example: 'public.ecr.aws/g2n4p2m7/margo:1.0.0' or 'oci://public.ecr.aws/g2n4p2m7/margo:1.0.0'

    Returns:
        A ResolvedRemoteDescriptor containing the normalized URI, the path to the pulled
        app.yaml, and a live TemporaryDirectory handle.

    Raises:
        ValueError: If URI is malformed, artifact is not Margo, or descriptor layer is not found
            in the pulled manifest.
        CredentialsExpiredError: If credentials for the registry have expired.
        Exception: If manifest fetch, pull, or other registry operation fails.

    The temp directory is NOT automatically cleaned up. The caller must use
    the returned handle in a finally block:

        resolver = resolve_remote_descriptor(uri)
        try:
            # use resolver.app_yaml_path
        finally:
            resolver.temp_dir.cleanup()
    """
    # Prepare OCI retrieval: normalize URI, validate, check credentials, fetch manifest once
    # This shared step avoids credential and manifest re-fetch when pull_prepared_context
    # (and oras-py's internal Registry.pull) execute.
    prepared = pull_service.prepare_oci_retrieval(uri)

    # Require PackageType.MARGO — reject compose, quadlet, unknown before pull
    if prepared.package_type != PackageType.MARGO:
        actual_type = prepared.manifest.get("artifactType") or "unknown"
        raise ValueError(
            f"Artifact at {prepared.normalized_uri} is not a Margo application descriptor "
            f"(type: {actual_type}). "
            f"Run 'margot fetch {prepared.normalized_uri}' to inspect the raw manifest."
        )

    # Create temporary directory for pull
    temp_dir = TemporaryDirectory(prefix="margot-remote-")
    try:
        # Pull the Margo artifact with recursive=False, using the prepared context
        pulled_paths = pull_service.pull_prepared_context(prepared, temp_dir.name, recursive=False)
        console.info(f"Pulled {len(pulled_paths)} layer(s).")

        # Locate descriptor layer by mediaType, matching to pulled paths
        # Layers and pulled_paths are in the same order from oras-py's pull
        descriptor_layer_index = _find_descriptor_layer_index(prepared.manifest)

        if descriptor_layer_index is None:
            # Clean up before raising
            temp_dir.cleanup()
            msg = (
                f"Artifact at {prepared.normalized_uri} is a Margo application descriptor "
                f"but has no layer with mediaType={MARGO_DESCRIPTION_MEDIA_TYPE}. "
                "Verify the artifact is valid."
            )
            raise ValueError(msg)  # noqa: TRY301

        # Get the path for this layer (same order as manifest layers)
        if descriptor_layer_index >= len(pulled_paths):
            temp_dir.cleanup()
            msg = "Internal error: descriptor layer index exceeds pulled paths count."
            raise ValueError(msg)  # noqa: TRY301

        app_yaml_path = pulled_paths[descriptor_layer_index]
        console.info(f"Application description located: {app_yaml_path}")
        return ResolvedRemoteDescriptor(
            normalized_uri=prepared.normalized_uri,
            app_yaml_path=app_yaml_path,
            temp_dir=temp_dir,
        )
    except Exception:
        # Clean up on any exception
        temp_dir.cleanup()
        raise


def _find_descriptor_layer_index(manifest: dict[str, Any]) -> int | None:
    """Find the index of the descriptor layer in a manifest's layers list.

    Locates the first layer with mediaType == MARGO_DESCRIPTION_MEDIA_TYPE.
    If more than one layer matches, logs a warning with all matching layers
    and returns the index of the first match.

    Args:
        manifest: OCI manifest dict.

    Returns:
        The index of the first descriptor layer, or None if no matching layer.
    """
    layers: list[dict[str, Any]] = manifest.get("layers", [])
    matching_indices: list[int] = []

    for idx, layer in enumerate(layers):
        if layer.get("mediaType") == MARGO_DESCRIPTION_MEDIA_TYPE:
            matching_indices.append(idx)

    if not matching_indices:
        return None

    if len(matching_indices) > 1:
        # Warn about multiple matches, but use the first
        layer_descriptions: list[str] = []
        for idx in matching_indices:
            layer = layers[idx]
            annotations = layer.get("annotations") or {}
            title = annotations.get("org.opencontainers.image.title", layer.get("digest", "unknown")[:12])
            layer_descriptions.append(f"  - {title} (digest: {layer.get('digest', 'unknown')[:12]})")
        console.warning(
            "Multiple descriptor layers found in manifest; using first match:\n" + "\n".join(layer_descriptions)
        )

    return matching_indices[0]
