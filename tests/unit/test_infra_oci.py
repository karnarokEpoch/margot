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

    def test_pull_returns_list_of_paths(self, mocker: Any) -> None:
        """pull() should return the list of paths from the underlying client."""
        mock_lib = MagicMock()
        mock_lib.pull.return_value = ["/tmp/a", "/tmp/b"]
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        client = OrasClient()
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", "/tmp")
        assert result == ["/tmp/a", "/tmp/b"]
        mock_lib.pull.assert_called_once_with(target="public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir="/tmp")

    def test_pull_returns_empty_list_when_client_returns_empty_list(self, mocker: Any) -> None:
        """pull() should return [] when the underlying client returns an empty list (no layers pulled)."""
        mock_lib = MagicMock()
        mock_lib.pull.return_value = []
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        client = OrasClient()
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", "/tmp")
        assert result == []

    def test_pull_normalizes_none_to_empty_list(self, mocker: Any) -> None:
        """pull() should return [] when the underlying client returns None."""
        mock_lib = MagicMock()
        mock_lib.pull.return_value = None
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        client = OrasClient()
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", "/tmp")
        assert result == []

    def test_pull_normalizes_non_list_to_empty_list(self, mocker: Any) -> None:
        """pull() should return [] when the underlying client returns a non-list value."""
        mock_lib = MagicMock()
        mock_lib.pull.return_value = "oops"
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        client = OrasClient()
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", "/tmp")
        assert result == []

    def test_download_blob_returns_outfile(self, mocker: Any) -> None:
        """download_blob() should return the outfile path after downloading."""
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        client = OrasClient()
        result = client.download_blob("public.ecr.aws/g2n4p2m7/margo:1.0.0", "sha256:abc", "/tmp/out.tgz")
        assert result == "/tmp/out.tgz"
        mock_lib.download_blob.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0", "sha256:abc", "/tmp/out.tgz")

    def test_login_delegates_to_client(self, mocker: Any) -> None:
        """login() should delegate to the underlying client with correct kwargs."""
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        client = OrasClient()
        client.login(hostname="public.ecr.aws", username="AWS", password="token")
        mock_lib.login.assert_called_once_with(username="AWS", password="token", hostname="public.ecr.aws")

    def test_logout_delegates_to_client(self, mocker: Any) -> None:
        """logout() should delegate to the underlying client with correct kwargs."""
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        client = OrasClient()
        client.logout(hostname="public.ecr.aws")
        mock_lib.logout.assert_called_once_with(hostname="public.ecr.aws")


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

    def test_pull_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """pull() should emit debug message when debug=True."""
        console.set_debug(True)
        mock_lib = MagicMock()
        mock_lib.pull.return_value = []
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        out, err = capture_console
        client = OrasClient()
        client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", "/tmp")
        assert "Pull layers:" in err.getvalue()
        assert out.getvalue() == ""

    def test_download_blob_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """download_blob() should emit debug message when debug=True."""
        console.set_debug(True)
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        out, err = capture_console
        client = OrasClient()
        client.download_blob("public.ecr.aws/g2n4p2m7/margo:1.0.0", "sha256:abc", "/tmp/out.tgz")
        assert "Download blob:" in err.getvalue()

    def test_login_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """login() should emit debug message when debug=True."""
        console.set_debug(True)
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        out, err = capture_console
        client = OrasClient()
        client.login(hostname="public.ecr.aws", username="AWS", password="token")
        assert "Login:" in err.getvalue()

    def test_logout_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """logout() should emit debug message when debug=True."""
        console.set_debug(True)
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)
        out, err = capture_console
        client = OrasClient()
        client.logout(hostname="public.ecr.aws")
        assert "Logout:" in err.getvalue()
