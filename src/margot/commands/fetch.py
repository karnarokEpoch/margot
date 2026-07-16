"""Fetch command: retrieve and display OCI artifact manifest."""

from typing import Any

from rich import print as rprint
from rich.json import JSON
from typer import echo

from margot.services import fetch as fetch_service


def fetch(uri: str) -> None:
    """
    Fetch and display the manifest of an OCI artifact.

    Args:
        uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)
    """
    try:
        manifest: dict[str, Any] = fetch_service.fetch_manifest(uri)
        rprint(JSON.from_dict(manifest, indent=2))
    # TODO(@karnarokEpoch): Do not catch blind exception: `Exception`
    except Exception as e:
        echo(f"Error fetching manifest: {e}", err=True)
        # TODO(@karnarokEpoch): Within an `except` clause
        # raise exceptions with `raise ... from err` or `raise ... from None`
        raise SystemExit(1)
