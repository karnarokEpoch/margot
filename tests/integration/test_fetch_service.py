"""Integration tests for services/fetch.py."""

from typing import Any
from unittest.mock import MagicMock

from pytest import raises

from margot.services import fetch


class TestFetchService:
    """Tests for fetch_manifest() service."""

    def test_fetch_manifest_calls_oras_client(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """Should call OrasClient.get_manifest with the URI."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        mock_client.get_manifest.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        assert result == mock_manifest

    def test_fetch_manifest_propagates_exception(self, mocker: Any) -> None:
        """Should propagate exceptions from OrasClient."""
        mock_client = MagicMock()
        mock_client.get_manifest.side_effect = Exception("Registry error")
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        with raises(Exception, match="Registry error"):
            fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

    def test_fetch_manifest_returns_manifest(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """Should return the manifest dict from OrasClient."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        assert isinstance(result, dict)
        assert "schemaVersion" in result
