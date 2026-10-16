"""Fetch command: retrieve and display OCI artifact manifest."""

from typing import Any

from oras.auth import AuthenticationException
from requests.exceptions import RequestException

from margot import console
from margot.infra.credentials import CredentialsExpiredError
from margot.infra.oci import OciRegistryError
from margot.services import fetch as fetch_service


def fetch(uri: str) -> None:
    """
    Fetch and display the manifest of an OCI artifact.

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)
    """
    try:
        manifest: dict[str, Any] = fetch_service.fetch_manifest(uri)
        console.print_json(manifest)
    except (AuthenticationException, CredentialsExpiredError, OciRegistryError, PermissionError, RequestException) as e:
        console.fatal(f"Error fetching manifest: {e}", code=4)
    except ValueError as e:
        console.fatal(f"Error fetching manifest: {e}", code=3)
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Error fetching manifest: {e}", code=1)
