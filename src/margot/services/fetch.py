"""Fetch service: orchestrate manifest retrieval."""

from typing import Any

from margot.infra import oci


def fetch_manifest(uri: str) -> dict[str, Any]:
    """
    Fetch an OCI artifact manifest by URI.

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/org/repo:tag)

    Returns:
        Manifest dict from the registry.

    Raises:
        ValueError: If URI is malformed.
        Exception: If fetch fails.
    """
    # TODO(kiro): Light URI validation (non-empty, has :tag)
    client = oci.OrasClient()
    return client.get_manifest(uri)
