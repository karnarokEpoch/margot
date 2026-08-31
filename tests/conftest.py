"""Shared test fixtures."""

from io import StringIO
import sys
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


@fixture
def capture_console():
    """Replace _get_stdout/_get_stderr with mocks for assertion."""
    out = StringIO()
    err = StringIO()
    original_get_stdout = _console._get_stdout  # noqa: SLF001
    original_get_stderr = _console._get_stderr  # noqa: SLF001

    def mock_get_stdout():
        return Console(file=out, width=200, no_color=True)

    def mock_get_stderr():
        return Console(file=err, width=200, no_color=True)

    _console._get_stdout = mock_get_stdout  # noqa: SLF001
    _console._get_stderr = mock_get_stderr  # noqa: SLF001

    yield out, err

    _console._get_stdout = original_get_stdout  # noqa: SLF001
    _console._get_stderr = original_get_stderr  # noqa: SLF001


@fixture(autouse=False)
def reset_console():
    """Reset verbose and debug flags to default state."""
    _console.set_verbose(False)
    _console.set_debug(False)
    yield
    _console.set_verbose(False)
    _console.set_debug(False)


@fixture
def force_color():
    """Force ANSI color output regardless of the runner's tty/environment detection.

    Rich decides whether to emit ANSI codes — and which color system — by inspecting
    `isatty()` and environment variables (`TERM`, `COLORTERM`). That decision is
    deliberately environment-dependent in production (so piped/redirected output stays
    plain), but it makes any test asserting on raw escape codes flaky across machines and
    CI runners: `force_terminal=True` alone only pins the on/off decision, not the color
    system, so a CI runner with no `TERM`/`COLORTERM` set still falls back to Rich's
    "standard" 16-color palette and downgrades named colors like `orange3` (which needs
    256-color `38;5;172`) to the nearest basic ANSI color. Pinning `color_system="256"`
    fixes both the on/off decision and the palette, independent of where the test runs.
    """
    original_get_stdout = _console._get_stdout  # noqa: SLF001
    original_get_stderr = _console._get_stderr  # noqa: SLF001

    def forced_get_stdout():
        return Console(file=sys.stdout, force_terminal=True, no_color=False, color_system="256")

    def forced_get_stderr():
        return Console(file=sys.stderr, force_terminal=True, no_color=False, color_system="256")

    _console._get_stdout = forced_get_stdout  # noqa: SLF001
    _console._get_stderr = forced_get_stderr  # noqa: SLF001

    yield

    _console._get_stdout = original_get_stdout  # noqa: SLF001
    _console._get_stderr = original_get_stderr  # noqa: SLF001
