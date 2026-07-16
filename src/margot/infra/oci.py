"""OCI registry adapter: oras-py wrapper."""

from typing import Any


class OrasClient:
    """Wrapper around oras.client.OrasClient for anonymous OCI operations."""

    def __init__(self) -> None:
        """Initialize OrasClient."""
        # TODO(kiro): Initialize oras.client.OrasClient

    def get_manifest(self, uri: str) -> dict[str, Any]:
        """
        Fetch the manifest of an OCI artifact.

        Args:
            uri: Full OCI reference (e.g. public.ecr.aws/org/repo:tag)

        Returns:
            Manifest dict from the registry.

        Raises:
            Exception: If fetch fails.
        """
        # TODO(kiro): Call oras.client.OrasClient.remote.get_manifest(uri)
        raise NotImplementedError("OrasClient.get_manifest not yet implemented")
