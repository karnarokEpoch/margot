"""OCI registry adapter: oras-py wrapper."""

from typing import Any

from oras.client import OrasClient as OrasClientLib

from margot import console


class OrasClient:
    """Wrapper around oras.client.OrasClient for anonymous OCI operations.

    Provides pull() for bulk layer download and download_blob() for individual blob retrieval.
    """

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
        console.debug(f"GET manifest: {uri}")
        return self._client.get_manifest(uri)

    def pull(self, uri: str, outdir: str) -> list[str]:
        """
        Pull OCI artifact layers to outdir.

        Deprecated:
            Production code should use download_blob() directly via the layer loop
            in services/pull.py. This method is retained for legacy test compatibility
            and for non-compose/quadlet artifact types.

        Args:
            uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)
            outdir: Directory to write layer blobs to.

        Returns:
            List of paths to written files.

        Raises:
            Exception: If pull fails.
        """
        console.debug(f"Pull layers: {uri} → {outdir}")
        result = self._client.pull(target=uri, outdir=outdir)
        if isinstance(result, list):
            return result
        return []

    def download_blob(self, uri: str, digest: str, outfile: str) -> str:
        """
        Download a single blob by digest to outfile.

        Args:
            uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0).
                Used to resolve the registry/repository container.
            digest: The blob digest (e.g. 'sha256:abc...').
            outfile: Destination file path (created by oras-py).

        Returns:
            The outfile path.

        Raises:
            Exception: If download fails.
        """
        console.debug(f"Download blob: {digest} → {outfile}")
        self._client.download_blob(uri, digest, outfile)
        return outfile

    def login(self, hostname: str, username: str, password: str) -> None:
        """
        Authenticate with an OCI registry.

        Args:
            hostname: Registry hostname (e.g. 'public.ecr.aws').
            username: Username (e.g. 'AWS' for ECR).
            password: Password or token.
        """
        console.debug(f"Login: {hostname} as {username}")
        self._client.login(username=username, password=password, hostname=hostname)

    def logout(self, hostname: str) -> None:
        """
        Remove stored credentials for registry.

        Args:
            hostname: Registry hostname.
        """
        console.debug(f"Logout: {hostname}")
        self._client.logout(hostname=hostname)
