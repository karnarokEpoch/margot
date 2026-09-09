"""Pull service: orchestrate OCI artifact retrieval to disk."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from margot import console
from margot.domain import uri as uri_domain
from margot.domain.app_description import extract_component_refs
from margot.domain.layers import COMPOSE_LAYER_MEDIA_TYPE, QUADLET_LAYER_MEDIA_TYPE, resolve_filename
from margot.domain.models import (
    _ARTIFACT_TYPE_MAP,
    PackageType,
    artifact_type_to_package_type,
)
from margot.domain.uri import extract_tag, validate_semver_tag
from margot.infra import credentials, oci

_PAYLOAD_MEDIA_TYPES: dict[PackageType, str] = {
    PackageType.COMPOSE: COMPOSE_LAYER_MEDIA_TYPE,
    PackageType.QUADLET: QUADLET_LAYER_MEDIA_TYPE,
}

_MEDIA_TYPE_NAMES: dict[str, str] = {v: k.name.lower() for k, v in _PAYLOAD_MEDIA_TYPES.items()}


@dataclass
class _LayerContext:
    """Context for downloading compose/quadlet layers."""

    client: oci.OrasClient
    uri: str
    outdir: str
    matching_layers: list[dict[str, Any]]
    manifest_annotations: dict[str, Any] | None
    force: bool


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


def _pull_recursive_components(outdir: str, root_paths: list[str], force: bool) -> list[str]:
    """Pull declared components from a margo app.yaml into component subdirectories.

    Locates app.yaml in the root_paths, parses it, extracts component refs,
    and recursively pulls each into outdir/<component-name>/.

    Args:
        outdir: Root output directory (where app.yaml was pulled).
        root_paths: List of paths that were pulled for the root artifact.
        force: Pass-through to recursive pull_artifact calls.

    Returns:
        Combined list of all paths: root_paths + component paths in declaration order.
    """
    result = root_paths.copy()

    # Locate app.yaml in the pulled paths
    app_yaml_path = None
    for path in root_paths:
        if Path(path).name == "app.yaml":
            app_yaml_path = path
            break

    if app_yaml_path is None:
        console.warning("app.yaml not found in pulled layers; skipping component recursion.")
        return result

    # Load and parse app.yaml
    try:
        with Path(app_yaml_path).open(encoding="utf-8") as f:
            app_doc = yaml.safe_load(f)
        if not app_doc:
            console.warning("app.yaml is empty or unparseable; skipping component recursion.")
            return result
    except (OSError, yaml.YAMLError) as e:
        console.warning(f"Failed to load app.yaml: {e}; skipping component recursion.")
        return result

    # Extract component refs
    comp_refs, skipped_names = extract_component_refs(app_doc)

    # Warn about skipped components
    for skipped in skipped_names:
        console.warning(f"Skipping component '{skipped}': missing repository or revision properties.")

    # Recursively pull each component
    for comp_ref in comp_refs:
        component_outdir = str(Path(outdir) / comp_ref.name)
        try:
            comp_paths = pull_artifact(
                comp_ref.ref,
                outdir=component_outdir,
                force=force,
                force_type=None,
                recursive=False,  # Components don't have sub-components in this model
            )
            console.info(f"Pulled component '{comp_ref.name}': {len(comp_paths)} file(s).")
            result.extend(comp_paths)
        except Exception as e:  # noqa: BLE001
            console.warning(f"Failed to pull component '{comp_ref.name}': {e}")

    return result


def _handle_unknown_artifact(
    client: oci.OrasClient,
    uri: str,
    outdir: str,
    manifest: dict[str, Any],
    force: bool,
) -> list[str]:
    """Handle pull of unknown artifact type.

    Args:
        client: OCI client.
        uri: Full OCI reference.
        outdir: Output directory.
        manifest: Manifest dict.
        force: Whether force mode is enabled.

    Returns:
        List of pulled paths.

    Raises:
        ValueError: If artifact type is unknown and force=False.
    """
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


def _handle_margo_artifact(
    client: oci.OrasClient,
    uri: str,
    outdir: str,
    recursive: bool,
    force: bool,
) -> list[str]:
    """Handle pull of Margo artifact type (with optional component recursion).

    Args:
        client: OCI client.
        uri: Full OCI reference.
        outdir: Output directory.
        recursive: Whether to recursively pull declared components.
        force: Whether force mode is enabled.

    Returns:
        List of pulled paths (root + component paths).
    """
    pulled_paths = client.pull(uri=uri, outdir=outdir)
    console.info(f"Pulled {len(pulled_paths)} layer(s).")
    result = pulled_paths or []

    # Handle recursive component pulling if requested
    if recursive:
        result = _pull_recursive_components(outdir, result, force)

    return result


def _download_compose_quadlet_layers(ctx: _LayerContext) -> list[str]:
    """Download individual layers for compose/quadlet artifacts.

    Args:
        ctx: Layer download context.

    Returns:
        List of paths to downloaded files.
    """
    result: list[str] = []

    for layer in ctx.matching_layers:
        # Resolve desired filename
        desired_name = resolve_filename(layer, ctx.manifest_annotations, force=ctx.force)

        # Fall back to digest-based name if no name resolved
        if desired_name is None:
            digest_hex = layer["digest"].split(":", 1)[-1][:12]
            desired_name = digest_hex
        else:
            console.info(f"Layer filename resolved: {desired_name}.")

        outfile = str(Path(ctx.outdir) / desired_name)
        ctx.client.download_blob(ctx.uri, layer["digest"], outfile)
        result.append(outfile)

    return result


def _validate_and_filter_layers(
    package_type: PackageType,
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Validate and filter layers for compose/quadlet artifacts.

    Args:
        package_type: PackageType (COMPOSE or QUADLET).
        manifest: Manifest dict.

    Returns:
        Tuple of (matching_layers, manifest_annotations).

    Raises:
        ValueError: If no matching layers found.
    """
    target_media_type = _PAYLOAD_MEDIA_TYPES[package_type]
    layers: list[dict[str, Any]] = manifest.get("layers") or []
    matching_layers = [layer for layer in layers if layer.get("mediaType") == target_media_type]

    if not matching_layers:
        available = _available_layer_types(layers)
        raise ValueError(f"No layer with mediaType '{target_media_type}' found.\n{available}")

    manifest_annotations: dict[str, Any] | None = manifest.get("annotations")
    return matching_layers, manifest_annotations


def _handle_compose_or_quadlet_artifact(
    client: oci.OrasClient,
    uri: str,
    outdir: str,
    package_type_and_manifest: tuple[PackageType, dict[str, Any]],
    force: bool = False,
) -> list[str]:
    """Handle pull of compose or quadlet artifact type.

    Args:
        client: OCI client.
        uri: Full OCI reference.
        outdir: Output directory.
        package_type_and_manifest: Tuple of (PackageType, manifest dict).
        force: Whether force mode is enabled (default: False).

    Returns:
        List of pulled paths.

    Raises:
        ValueError: If no matching layers found.
    """
    package_type, manifest = package_type_and_manifest
    matching_layers, manifest_annotations = _validate_and_filter_layers(package_type, manifest)
    ctx = _LayerContext(
        client=client,
        uri=uri,
        outdir=outdir,
        matching_layers=matching_layers,
        manifest_annotations=manifest_annotations,
        force=force,
    )
    result = _download_compose_quadlet_layers(ctx)

    console.info(f"Pulled {len(result)} layer(s).")
    return result


def pull_artifact(
    uri: str,
    outdir: str = ".",
    *,
    force: bool = False,
    force_type: PackageType | None = None,
    recursive: bool = False,
) -> list[str]:
    """
    Pull OCI artifact layers to outdir.

    For compose/quadlet artifacts: downloads matching layers individually, resolves filenames.
    For margo artifacts: uses client.pull() for bulk download, and if recursive=True,
    also pulls declared component artifacts into subdirectories named after each component.
    For other types (unknown): delegates to client.pull() for bulk download.

    Steps:
    1. Normalize URI by stripping 'oci://' scheme if present.
    2. Validate URI (via domain/uri.py).
    3. Guard: force_type requires force.
    4. SemVer gate: reject non-SemVer tags unless force=True.
    5. Create outdir.
    6. Fetch manifest.
    7. Detect artifact type via the artifactType field; override with force_type if set.
    8. If package_type is MARGO:
       a. Pull root layers via client.pull().
       b. If recursive=True: locate app.yaml in pulled layers, extract component refs,
          and recursively pull each component into outdir/<component-name>/.
    9. If package_type not in _PAYLOAD_MEDIA_TYPES: use client.pull() (unknown types).
    10. Otherwise (compose/quadlet): own the layer loop.
        a. Get target mediaType for this package_type.
        b. Filter manifest layers by that mediaType.
        c. Hard-fail if no matching layers found.
        d. For each layer: resolve filename and download individually.
    11. Return flat list of all written file paths (root + component paths in order).

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0 or oci://public.ecr.aws/g2n4p2m7/margo:1.0.0).
        outdir: Destination directory (created if needed).
        force: Bypass SemVer gate and malicious annotation checks.
        force_type: Override detected artifact type interpretation.
        recursive: If True and artifact is margo, also pull declared components. No-op for other types.

    Returns:
        List of paths to written files (root first, then component paths in order).

    Raises:
        ValueError: If URI is malformed.
        ValueError: If tag is not valid SemVer and force=False.
        ValueError: If compose/quadlet artifact has no matching layers.
        ValueError: If artifact type is unknown and force=False.
        CredentialsExpiredError: If credentials for the registry have expired.
        Exception: If pull or manifest fetch fails.
    """
    # Normalize URI by stripping scheme
    uri = uri_domain.strip_scheme(uri)

    uri_domain.validate_uri(uri)
    console.info(f"URI validated: {uri}")

    tag = extract_tag(uri)
    if not validate_semver_tag(tag) and not force:
        raise ValueError(f"Tag '{tag}' is not valid SemVer. Use --force to pull anyway.")
    console.info(f"Tag '{tag}' is valid SemVer.")

    Path(outdir).mkdir(parents=True, exist_ok=True)
    console.info(f"Output directory ready: {outdir}")

    hostname = uri_domain.extract_hostname(uri)
    console.info(f"Checking credentials for {hostname}")
    credentials.check_credentials(hostname)

    client = oci.OrasClient(hostname=hostname)
    manifest: dict[str, Any] = client.get_manifest(uri)
    console.info("Manifest fetched.")

    artifact_type: str | None = manifest.get("artifactType")
    package_type = artifact_type_to_package_type(artifact_type)
    console.info(f"Detected artifact type: {package_type.value if package_type else 'unknown'}")

    if force_type is not None:
        package_type = force_type
        console.info(f"Artifact type overridden to: {force_type.value}")

    # Dispatch to type-specific handlers
    if package_type == PackageType.UNKNOWN:
        return _handle_unknown_artifact(client, uri, outdir, manifest, force)

    if package_type == PackageType.MARGO:
        return _handle_margo_artifact(client, uri, outdir, recursive, force)

    # Handle compose/quadlet
    return _handle_compose_or_quadlet_artifact(client, uri, outdir, (package_type, manifest), force)
