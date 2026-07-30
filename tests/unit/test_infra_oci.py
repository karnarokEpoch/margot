"""Unit tests for infra/oci.py OrasClient wrapper."""

from typing import Any

from oras.client import OrasClient as OrasClientLib

from margot import console
from margot.infra.oci import OrasClient

FAKE_OUTDIR = "/fake/outdir"
FAKE_FILE_A = "/fake/outdir/a"
FAKE_FILE_B = "/fake/outdir/b"
FAKE_BLOB_OUT = "/fake/outdir/out.tgz"


class TestOrasClient:
    """Tests for OrasClient."""

    def test_oras_client_init(self, mocker: Any) -> None:
        """Should initialize OrasClient instance without error."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        client = OrasClient()
        assert client is not None

    def test_oras_client_has_get_manifest(self, mocker: Any) -> None:
        """Should have get_manifest method."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        client = OrasClient()
        assert hasattr(client, "get_manifest")
        assert callable(client.get_manifest)

    def test_oras_client_inherits_from_oras_client_lib(self, mocker: Any) -> None:
        """Should inherit from OrasClientLib."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        client = OrasClient()
        assert isinstance(client, OrasClientLib)

    def test_pull_returns_list_of_paths(self, mocker: Any) -> None:
        """pull() should return the list of paths from the underlying client."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.pull", return_value=[FAKE_FILE_A, FAKE_FILE_B])
        client = OrasClient()
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", FAKE_OUTDIR)
        assert result == [FAKE_FILE_A, FAKE_FILE_B]

    def test_pull_returns_empty_list_when_client_returns_empty_list(self, mocker: Any) -> None:
        """pull() should return [] when the underlying client returns an empty list (no layers pulled)."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.pull", return_value=[])
        client = OrasClient()
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", FAKE_OUTDIR)
        assert result == []

    def test_pull_normalizes_none_to_empty_list(self, mocker: Any) -> None:
        """pull() should return [] when the underlying client returns None."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.pull", return_value=None)
        client = OrasClient()
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", FAKE_OUTDIR)
        assert result == []

    def test_pull_normalizes_non_list_to_empty_list(self, mocker: Any) -> None:
        """pull() should return [] when the underlying client returns a non-list value."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.pull", return_value="oops")
        client = OrasClient()
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", FAKE_OUTDIR)
        assert result == []

    def test_download_blob_returns_outfile(self, mocker: Any) -> None:
        """download_blob() should return the outfile path after downloading."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_download = mocker.patch("margot.infra.oci.OrasClientLib.download_blob")
        client = OrasClient()
        result = client.download_blob("public.ecr.aws/g2n4p2m7/margo:1.0.0", "sha256:abc", FAKE_BLOB_OUT)
        assert result == FAKE_BLOB_OUT
        mock_download.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0", "sha256:abc", FAKE_BLOB_OUT)

    def test_login_delegates_to_client(self, mocker: Any) -> None:
        """login() should delegate to the underlying client with correct kwargs."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_login = mocker.patch("margot.infra.oci.OrasClientLib.login")
        client = OrasClient()
        client.login(hostname="public.ecr.aws", username="AWS", password="token")
        mock_login.assert_called_once_with(username="AWS", password="token", hostname="public.ecr.aws")

    def test_logout_delegates_to_client(self, mocker: Any) -> None:
        """logout() should delegate to the underlying client with correct kwargs."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_logout = mocker.patch("margot.infra.oci.OrasClientLib.logout")
        client = OrasClient()
        client.logout(hostname="public.ecr.aws")
        mock_logout.assert_called_once_with(hostname="public.ecr.aws")


class TestOciAdapterDebugLogging:
    """Tests for OrasClient with debug logging."""

    def test_get_manifest_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """get_manifest() should emit debug message when debug=True."""
        console.set_debug(True)
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest", return_value={})
        out, err = capture_console
        client = OrasClient()
        client.get_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        assert "GET manifest:" in err.getvalue()
        assert out.getvalue() == ""

    def test_get_manifest_no_debug_without_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """get_manifest() should not emit debug output when debug=False."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest", return_value={})
        _out, err = capture_console
        client = OrasClient()
        client.get_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        assert err.getvalue() == ""

    def test_pull_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """pull() should emit debug message when debug=True."""
        console.set_debug(True)
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.pull", return_value=[])
        out, err = capture_console
        client = OrasClient()
        client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", FAKE_OUTDIR)
        assert "Pull layers:" in err.getvalue()
        assert out.getvalue() == ""

    def test_download_blob_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """download_blob() should emit debug message when debug=True."""
        console.set_debug(True)
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.download_blob")
        _out, err = capture_console
        client = OrasClient()
        client.download_blob("public.ecr.aws/g2n4p2m7/margo:1.0.0", "sha256:abc", FAKE_BLOB_OUT)
        assert "Download blob:" in err.getvalue()

    def test_login_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """login() should emit debug message when debug=True."""
        console.set_debug(True)
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.login")
        _out, err = capture_console
        client = OrasClient()
        client.login(hostname="public.ecr.aws", username="AWS", password="token")
        assert "Login:" in err.getvalue()

    def test_logout_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """logout() should emit debug message when debug=True."""
        console.set_debug(True)
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.logout")
        _out, err = capture_console
        client = OrasClient()
        client.logout(hostname="public.ecr.aws")
        assert "Logout:" in err.getvalue()
