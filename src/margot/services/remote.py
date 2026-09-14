"""Remote OCI artifact resolver: pull and inspect remote Margo application descriptors.

This service handles the complete lifecycle of remote descriptor resolution:
- URI normalization and validation
- Manifest fetching and artifact-type checking
- Margo-only gating (compose/quadlet/unknown fail before pull)
- Pulling to a temporary directory (recursive=False)
- Root app.yaml location and validation
- Temporary directory cleanup responsibility (caller's finally block)

No Rich rendering or terminal output — pure data and exceptions.
"""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from margot import console
from margot.domain import uri as uri_domain
from margot.domain.models import PackageType, artifact_type_to_package_type
from margot.infra import credentials, oci
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

    Validates the URI, fetches the manifest, verifies that the artifact is a Margo
    application descriptor (rejects compose/quadlet/unknown), pulls the artifact
    with recursive=False, and locates the root app.yaml. The temporary directory
    remains live; cleanup is the caller's responsibility.

    Args:
        uri: Full OCI reference, optionally with 'oci://' scheme prefix.
            Example: 'public.ecr.aws/g2n4p2m7/margo:1.0.0' or 'oci://public.ecr.aws/g2n4p2m7/margo:1.0.0'

    Returns:
        A ResolvedRemoteDescriptor containing the normalized URI, the path to the pulled
        app.yaml, and a live TemporaryDirectory handle.

    Raises:
        ValueError: If URI is malformed, tagged OCI reference validation fails, artifact
            is not Margo, or app.yaml is not found in the pulled layers.
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
    # Normalize URI by stripping scheme
    normalized_uri = uri_domain.strip_scheme(uri)

    # Validate URI
    uri_domain.validate_uri(normalized_uri)
    console.info(f"URI validated: {normalized_uri}")

    # Extract hostname and check credentials
    hostname = uri_domain.extract_hostname(normalized_uri)
    console.info(f"Checking credentials for {hostname}")
    credentials.check_credentials(hostname)

    # Fetch manifest and check artifact type
    client = oci.OrasClient(hostname=hostname)
    manifest = client.get_manifest(normalized_uri)
    console.info("Manifest fetched.")

    artifact_type = manifest.get("artifactType")
    package_type = artifact_type_to_package_type(artifact_type)
    console.info(f"Detected artifact type: {package_type.value if package_type else 'unknown'}")

    # Require PackageType.MARGO — reject compose, quadlet, unknown before pull
    if package_type != PackageType.MARGO:
        actual_type = artifact_type or "unknown"
        raise ValueError(
            f"Artifact at {normalized_uri} is not a Margo application descriptor "
            f"(type: {actual_type}). "
            f"Run 'margot fetch {normalized_uri}' to inspect the raw manifest."
        )

    # Create temporary directory for pull
    temp_dir = TemporaryDirectory(prefix="margot-remote-")
    try:
        # Pull the Margo artifact with recursive=False
        pulled_paths = pull_service.pull_artifact(
            normalized_uri,
            outdir=temp_dir.name,
            recursive=False,
        )
        console.info(f"Pulled {len(pulled_paths)} layer(s).")

        # Locate app.yaml in pulled paths
        app_yaml_path = None
        for path in pulled_paths:
            if Path(path).name == "app.yaml":
                app_yaml_path = path
                break

        if app_yaml_path is None:
            # Clean up before raising
            temp_dir.cleanup()
            msg = (
                f"Artifact at {normalized_uri} is a Margo application descriptor "
                f"but has no root app.yaml layer. Verify the artifact is valid."
            )
            raise ValueError(msg)  # noqa: TRY301

        console.info(f"Application description located: {app_yaml_path}")
        return ResolvedRemoteDescriptor(
            normalized_uri=normalized_uri,
            app_yaml_path=app_yaml_path,
            temp_dir=temp_dir,
        )
    except Exception:
        # Clean up on any exception
        temp_dir.cleanup()
        raise
