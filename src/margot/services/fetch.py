"""Fetch service: orchestrate manifest retrieval."""

from typing import Any

from margot.domain import uri as uri_domain
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
    uri_domain.validate_uri(uri)
    client = oci.OrasClient()
    return client.get_manifest(uri)
