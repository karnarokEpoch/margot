"""Fetch command: retrieve and display OCI artifact manifest."""

from typing import Any

from rich import print as rprint
from rich.json import JSON

from margot import console
from margot.services import fetch as fetch_service


def fetch(uri: str) -> None:
    """
    Fetch and display the manifest of an OCI artifact.

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)
    """
    try:
        manifest: dict[str, Any] = fetch_service.fetch_manifest(uri)
        rprint(JSON.from_data(manifest, indent=2))
    except ValueError as e:
        console.fatal(f"Error fetching manifest: {e}")
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Error fetching manifest: {e}")
