"""Shared test fixtures."""

from io import StringIO
from typing import Any
from unittest.mock import MagicMock

from pytest import fixture
from rich.console import Console

import margot.console as _console


@fixture
def mock_oras_client(mocker: Any) -> MagicMock:
    """Mock OrasClient for infra layer tests."""
    return mocker.patch("margot.infra.oras.OrasClient")


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


@fixture()
def capture_console():
    """Replace _get_stdout/_get_stderr with mocks for assertion."""
    out = StringIO()
    err = StringIO()
    original_get_stdout = _console._get_stdout
    original_get_stderr = _console._get_stderr

    def mock_get_stdout():
        return Console(file=out)

    def mock_get_stderr():
        return Console(file=err)

    _console._get_stdout = mock_get_stdout
    _console._get_stderr = mock_get_stderr

    yield out, err

    _console._get_stdout = original_get_stdout
    _console._get_stderr = original_get_stderr


@fixture(autouse=False)
def reset_console():
    """Reset verbose and debug flags to default state."""
    _console.set_verbose(False)
    _console.set_debug(False)
    yield
    _console.set_verbose(False)
    _console.set_debug(False)
