"""OCI registry adapter: oras-py wrapper."""

from typing import Any

from oras.client import OrasClient as OrasClientLib


class OrasClient:
    """Wrapper around oras.client.OrasClient for anonymous OCI operations."""

    def __init__(self) -> None:
        """Initialize OrasClient for anonymous registry access."""
        self._client = OrasClientLib()

    def get_manifest(self, uri: str) -> dict[str, Any]:
        """
        Fetch the manifest of an OCI artifact.

        Args:
            uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)

        Returns:
            Manifest dict from the registry.

        Raises:
            Exception: If fetch fails.
        """
        return self._client.get_manifest(uri)

    def pull(self, uri: str, outdir: str) -> list[str]:
        """
        Pull OCI artifact layers to outdir.

        Args:
            uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)
            outdir: Directory to write layer blobs to.

        Returns:
            List of paths to written files.

        Raises:
            Exception: If pull fails.
        """
        result = self._client.pull(target=uri, outdir=outdir)
        if isinstance(result, list):
            return result
        return []
