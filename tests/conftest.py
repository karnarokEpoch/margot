"""Shared test fixtures."""

from typing import Any
from unittest.mock import MagicMock

from pytest import fixture


@fixture
def mock_oras_client(mocker: Any) -> MagicMock:
    """Mock OrasClient for infra layer tests."""
    return mocker.patch("margot.infra.oci.OrasClient")


@fixture
def mock_manifest() -> dict[str, Any]:
    """Sample OCI manifest response."""
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.margo.app.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "size": 2,
            "data": "e30=",
        },
        "layers": [
            {
                "mediaType": "application/vnd.margo.app.description.v1+yaml",
                "size": 128,
                "digest": "sha256:def456",
                "annotations": {"org.opencontainers.image.title": "margo.yaml"},
            }
        ],
    }
