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
    if not uri:
        raise ValueError("URI must not be empty")
    tag_sep = uri.rfind(":")
    if tag_sep == -1 or not uri[tag_sep + 1 :]:
        raise ValueError("URI must contain a tag separated by ':' (e.g. registry/repo:tag)")
    client = oci.OrasClient()
    return client.get_manifest(uri)
