"""Pull service: orchestrate OCI artifact retrieval to disk."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yaml import YAMLError, safe_load

from margot import console
from margot.domain import uri as uri_domain
from margot.domain.app_description import extract_component_refs
from margot.domain.layers import COMPOSE_LAYER_MEDIA_TYPE, QUADLET_LAYER_MEDIA_TYPE, resolve_filename
from margot.domain.models import (
    _ARTIFACT_TYPE_MAP,
    PackageType,
    artifact_type_to_package_type,
)
from margot.infra import credentials
from margot.infra.oci import OrasClient

_PAYLOAD_MEDIA_TYPES: dict[PackageType, str] = {
    PackageType.COMPOSE: COMPOSE_LAYER_MEDIA_TYPE,
    PackageType.QUADLET: QUADLET_LAYER_MEDIA_TYPE,
}

_MEDIA_TYPE_NAMES: dict[str, str] = {v: k.name.lower() for k, v in _PAYLOAD_MEDIA_TYPES.items()}


@dataclass(frozen=True)
class PreparedOCIRetrieval:
    """Internal context for a single prepared OCI retrieval operation.

    Encapsulates the results of OCI preparation: normalized URI, hostname, live client
    instance, fetched manifest, and detected package type. This context is reused across
    credential check, manifest fetch, and pull operations to avoid redundant I/O.

    Attributes:
        normalized_uri: The OCI reference in canonical form (no oci:// scheme).
        hostname: The registry hostname extracted from the URI.
        client: Live OrasClient instance, configured with credentials if available.
        manifest: The fetched OCI manifest dict.
        package_type: Detected PackageType (MARGO, COMPOSE, QUADLET, or UNKNOWN).
    """

    normalized_uri: str
    hostname: str
    client: OrasClient
    manifest: dict[str, Any]
    package_type: PackageType


@dataclass
class _LayerContext:
    """Context for downloading compose/quadlet layers."""

    client: OrasClient
    uri: str
    outdir: str
    matching_layers: list[dict[str, Any]]
    manifest_annotations: dict[str, Any] | None
    force: bool


def prepare_oci_retrieval(uri: str) -> PreparedOCIRetrieval:
    """Prepare an OCI retrieval: normalize, validate, check credentials, and fetch manifest once.

    This is the single point where URI validation, credential expiry check, and manifest
    fetch occur. The returned context is reused across pull operations to avoid redundant I/O.

    Args:
        uri: Full OCI reference, optionally with 'oci://' scheme prefix.
            Example: 'public.ecr.aws/g2n4p2m7/margo:1.0.0' or 'oci://public.ecr.aws/g2n4p2m7/margo:1.0.0'

    Returns:
        PreparedOCIRetrieval context with normalized URI, hostname, client, manifest, and package type.

    Raises:
        ValueError: If URI is malformed or tagged OCI reference validation fails.
        CredentialsExpiredError: If credentials for the registry have expired.
        Exception: If manifest fetch fails.
    """
    # Normalize URI by stripping scheme
    normalized_uri = uri_domain.strip_scheme(uri)

    # Validate URI
    uri_domain.validate_uri(normalized_uri)
    console.info(f"URI validated: {normalized_uri}")

    # Extract hostname and check credentials
    hostname = uri_domain.extract_hostname(normalized_uri)
    console.info(f"Checking credentials for {hostname}")
    credentials.check_credentials(hostname)

    # Create client with hostname to load stored credentials
    client = OrasClient(hostname=hostname)

    # Fetch manifest exactly once
    manifest: dict[str, Any] = client.get_manifest(normalized_uri)
    console.info("Manifest fetched.")

    # Detect artifact type
    artifact_type: str | None = manifest.get("artifactType")
    package_type = artifact_type_to_package_type(artifact_type)
    console.info(f"Detected artifact type: {package_type.value if package_type else 'unknown'}")

    return PreparedOCIRetrieval(
        normalized_uri=normalized_uri,
        hostname=hostname,
        client=client,
        manifest=manifest,
        package_type=package_type,
    )


def pull_prepared_context(
    prepared: PreparedOCIRetrieval,
    outdir: str,
    *,
    force: bool = False,
    force_type: PackageType | None = None,
    recursive: bool = False,
) -> list[str]:
    """Pull OCI artifact from a prepared context, avoiding credential and manifest re-fetch.

    Uses the manifest already in the prepared context and routes through type-specific
    handlers (margo, compose, quadlet, unknown).

    Args:
        prepared: PreparedOCIRetrieval context from prepare_oci_retrieval.
        outdir: Destination directory (created if needed).
        force: Bypass malicious annotation checks and unknown-type gate.
        force_type: Override detected artifact type.
        recursive: If margo, also pull declared components.

    Returns:
        List of paths to written files.

    Raises:
        ValueError: If compose/quadlet has no matching layers, or artifact type is unknown
            and force=False.
        Exception: If pull or layer download fails.
    """
    Path(outdir).mkdir(parents=True, exist_ok=True)
    console.info(f"Output directory ready: {outdir}")

    # Override package type if force_type is set
    package_type = force_type if force_type is not None else prepared.package_type

    # Dispatch to type-specific handlers
    if package_type == PackageType.UNKNOWN:
        return _handle_unknown_artifact(
            prepared.client,
            prepared.normalized_uri,
            outdir,
            prepared.manifest,
            force,
        )

    if package_type == PackageType.MARGO:
        return _handle_margo_artifact(prepared.client, prepared.normalized_uri, outdir, recursive, force)

    # Handle compose/quadlet
    return _handle_compose_or_quadlet_artifact(
        prepared.client,
        prepared.normalized_uri,
        outdir,
        (package_type, prepared.manifest),
        force,
    )


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
            app_doc = safe_load(f)
        if not app_doc:
            console.warning("app.yaml is empty or unparseable; skipping component recursion.")
            return result
    except (OSError, YAMLError) as e:
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
    client: OrasClient,
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
    client: OrasClient,
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
    client: OrasClient,
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

    Uses a shared prepared context (prepare_oci_retrieval) to centralize URI validation,
    credential checks, and manifest fetching — avoiding redundant I/O when oras-py's
    Registry.pull() polymorphically calls self.get_manifest() internally.

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0 or oci://public.ecr.aws/g2n4p2m7/margo:1.0.0).
        outdir: Destination directory (created if needed).
        force: Bypass malicious annotation checks and unknown-type gate.
        force_type: Override detected artifact type interpretation.
        recursive: If True and artifact is margo, also pull declared components. No-op for other types.

    Returns:
        List of paths to written files (root first, then component paths in order).

    Raises:
        ValueError: If URI is malformed.
        ValueError: If compose/quadlet artifact has no matching layers.
        ValueError: If artifact type is unknown and force=False.
        CredentialsExpiredError: If credentials for the registry have expired.
        Exception: If pull or manifest fetch fails.
    """
    # Prepare OCI retrieval: normalize URI, validate, check credentials, fetch manifest once
    prepared = prepare_oci_retrieval(uri)

    # Use prepared context for pull, passing through force and recursive flags
    return pull_prepared_context(
        prepared,
        outdir,
        force=force,
        force_type=force_type,
        recursive=recursive,
    )
