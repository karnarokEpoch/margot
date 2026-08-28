"""Unit tests for infra/oci.py OrasClient wrapper."""

import logging
from typing import Any

from oras.client import OrasClient as OrasClientLib

from margot import console
from margot.infra.oci import OrasClient, _OrasLogHandler

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

    def test_oras_client_init_without_hostname_does_not_load_configs(self, mocker: Any) -> None:
        """Constructing without a hostname should not call auth.load_configs."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_auth = mocker.MagicMock()
        mocker.patch.object(OrasClient, "auth", mock_auth, create=True)
        OrasClient()
        mock_auth.load_configs.assert_not_called()

    def test_oras_client_init_with_hostname_loads_configs(self, mocker: Any) -> None:
        """Constructing with a hostname should trigger credential loading for that host."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_auth = mocker.MagicMock()
        mocker.patch.object(OrasClient, "auth", mock_auth, create=True)
        mock_container = mocker.MagicMock()
        mock_get_container = mocker.patch.object(OrasClient, "get_container", return_value=mock_container)
        OrasClient(hostname="public.ecr.aws")
        mock_get_container.assert_called_once_with("public.ecr.aws")
        mock_auth.load_configs.assert_called_once_with(mock_container)

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
        mock_container = mocker.MagicMock()
        mocker.patch.object(OrasClient, "get_container", return_value=mock_container)
        client = OrasClient()
        result = client.download_blob("public.ecr.aws/g2n4p2m7/margo:1.0.0", "sha256:abc", FAKE_BLOB_OUT)
        assert result == FAKE_BLOB_OUT
        mock_download.assert_called_once_with(container=mock_container, digest="sha256:abc", outfile=FAKE_BLOB_OUT)

    def test_oras_logger_configured_on_init(self, mocker: Any) -> None:
        """After OrasClient(), oras.logger logger should have an _OrasLogHandler."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        OrasClient()
        oras_logger = logging.getLogger("oras.logger")
        assert any(isinstance(h, _OrasLogHandler) for h in oras_logger.handlers)

    def test_oras_logger_level_debug_when_debug_mode(self, mocker: Any) -> None:
        """Logger level should be DEBUG when console debug mode is active."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.console.is_debug", return_value=True)
        mocker.patch("margot.infra.oci.console.is_verbose", return_value=True)
        OrasClient()
        oras_logger = logging.getLogger("oras.logger")
        assert oras_logger.level == logging.DEBUG

    def test_oras_logger_level_info_when_verbose_only(self, mocker: Any) -> None:
        """Logger level should be INFO when verbose but not debug."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.console.is_debug", return_value=False)
        mocker.patch("margot.infra.oci.console.is_verbose", return_value=True)
        OrasClient()
        oras_logger = logging.getLogger("oras.logger")
        assert oras_logger.level == logging.INFO

    def test_oras_logger_level_warning_when_quiet(self, mocker: Any) -> None:
        """Logger level should be WARNING when neither verbose nor debug."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.console.is_debug", return_value=False)
        mocker.patch("margot.infra.oci.console.is_verbose", return_value=False)
        OrasClient()
        oras_logger = logging.getLogger("oras.logger")
        assert oras_logger.level == logging.WARNING

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
        mocker.patch("margot.infra.oci.credentials.remove_docker_config_entry")
        client = OrasClient()
        client.logout(hostname="public.ecr.aws")
        mock_logout.assert_called_once_with(hostname="public.ecr.aws")

    def test_logout_removes_docker_config_entry(self, mocker: Any) -> None:
        """logout() should persist removal to the on-disk docker config file."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.logout")
        mock_remove = mocker.patch("margot.infra.oci.credentials.remove_docker_config_entry")
        client = OrasClient()
        client.logout(hostname="public.ecr.aws")
        mock_remove.assert_called_once_with("public.ecr.aws")


class TestOciAdapterDebugLogging:
    """Tests for OrasClient with debug logging."""

    def test_get_manifest_emits_debug_when_debug_mode(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """get_manifest() should emit debug message when debug=True."""
        console.set_debug(True)
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest", return_value={})
        mock_container = mocker.MagicMock()
        mocker.patch.object(OrasClient, "get_container", return_value=mock_container)
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
        mock_container = mocker.MagicMock()
        mocker.patch.object(OrasClient, "get_container", return_value=mock_container)
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
        mock_container = mocker.MagicMock()
        mocker.patch.object(OrasClient, "get_container", return_value=mock_container)
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
