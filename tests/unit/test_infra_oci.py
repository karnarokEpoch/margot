"""Unit tests for infra/oci.py OrasClient wrapper."""

from typing import Any
from unittest.mock import MagicMock

from margot import console
from margot.infra.oci import OrasClient


class TestOrasClient:
    """Tests for OrasClient."""

    def test_oras_client_init(self) -> None:
        """Should initialize OrasClient instance without error."""
        client = OrasClient()
        assert client is not None

    def test_oras_client_has_get_manifest(self) -> None:
        """Should have get_manifest method."""
        client = OrasClient()
        assert hasattr(client, "get_manifest")
        assert callable(client.get_manifest)

    def test_oras_client_has_internal_client(self) -> None:
        """Should have internal _client attribute."""
        client = OrasClient()
        assert hasattr(client, "_client")



class TestOciAdapterDebugLogging:
    """Tests for OrasClient with debug logging."""

    def test_get_manifest_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """get_manifest() should emit debug message when debug=True."""
        console.set_debug(True)
        mock_lib = MagicMock()
        mock_lib.get_manifest.return_value = {}
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        out, err = capture_console
        client = OrasClient()
        client.get_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        assert "GET manifest:" in err.getvalue()
        assert out.getvalue() == ""

    def test_get_manifest_no_debug_without_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """get_manifest() should not emit debug output when debug=False."""
        mock_lib = MagicMock()
        mock_lib.get_manifest.return_value = {}
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        _out, err = capture_console
        client = OrasClient()
        client.get_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        assert err.getvalue() == ""
