"""Unit tests for infra/oci.py OrasClient wrapper."""

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
