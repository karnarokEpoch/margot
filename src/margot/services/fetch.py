"""Fetch service: orchestrate manifest retrieval."""

from typing import Any

from margot import console
from margot.domain import uri as uri_domain
from margot.infra import credentials, oci


def fetch_manifest(uri: str) -> dict[str, Any]:
    """
    Fetch an OCI artifact manifest by URI.

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/org/repo:tag or oci://public.ecr.aws/org/repo:tag)

    Returns:
        Manifest dict from the registry.

    Raises:
        ValueError: If URI is malformed.
        CredentialsExpiredError: If credentials for the registry have expired.
        Exception: If fetch fails.
    """
    # Normalize URI by stripping scheme
    uri = uri_domain.strip_scheme(uri)

    uri_domain.validate_uri(uri)
    hostname = uri_domain.extract_hostname(uri)
    console.info(f"Checking credentials for {hostname}")
    credentials.check_credentials(hostname)
    console.info(f"Fetching manifest for: {uri}")
    client = oci.OrasClient(hostname=hostname)
    result = client.get_manifest(uri)
    console.info("Manifest retrieved.")
    return result
