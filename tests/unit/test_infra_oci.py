"""Unit tests for infra/oci.py OrasClient wrapper."""

from inspect import signature
import logging
from typing import Any

from oras.client import OrasClient as OrasClientLib
from oras.container import Container

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

    def test_download_blob_with_uri_string_returns_outfile(self, mocker: Any) -> None:
        """download_blob(uri_string, ...) should convert URI to Container and delegate to base class."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_download = mocker.patch("margot.infra.oci.OrasClientLib.download_blob")
        mock_container = mocker.MagicMock()
        mocker.patch.object(OrasClient, "get_container", return_value=mock_container)
        client = OrasClient()
        result = client.download_blob("public.ecr.aws/g2n4p2m7/margo:1.0.0", "sha256:abc", FAKE_BLOB_OUT)
        assert result == FAKE_BLOB_OUT
        mock_download.assert_called_once_with(mock_container, "sha256:abc", FAKE_BLOB_OUT)

    def test_download_blob_with_container_object_returns_outfile(self, mocker: Any) -> None:
        """download_blob(container_obj, ...) should pass Container through unchanged to base class."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_download = mocker.patch("margot.infra.oci.OrasClientLib.download_blob")
        # Create a real Container object to test polymorphic dispatch
        container_obj = Container(name="margo", registry="public.ecr.aws")
        client = OrasClient()
        result = client.download_blob(container_obj, "sha256:abc", FAKE_BLOB_OUT)
        assert result == FAKE_BLOB_OUT
        # Base class should receive the Container object unchanged
        mock_download.assert_called_once_with(container_obj, "sha256:abc", FAKE_BLOB_OUT)

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


class TestDownloadBlobPolymorphism:
    """Tests for download_blob() polymorphism: accepts both string URI and Container object."""

    def test_download_blob_accepts_both_string_and_container_types(self, mocker: Any) -> None:
        """Verify download_blob() signature accepts str | Container for the first parameter.

        This is a signature-level test verifying LSP compliance: the override
        must accept both string URIs (external callers) and Container objects
        (oras-py's internal polymorphic dispatch).
        """
        # Check the signature has the correct type hint
        sig = signature(OrasClient.download_blob)
        container_param = sig.parameters["container"]

        # Verify the type hint includes both str and Container
        assert container_param.annotation is not None
        annotation_str = str(container_param.annotation)
        # The annotation should mention both str and Container
        assert "str" in annotation_str
        assert "Container" in annotation_str


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


class TestGetManifestLSP:
    """Tests for OrasClient.get_manifest() Liskov Substitution Principle compatibility."""

    def test_get_manifest_with_string_uri_delegates_correctly(self, mocker: Any) -> None:
        """get_manifest(uri_string) should convert to Container and delegate to base class."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_base_get_manifest = mocker.patch(
            "margot.infra.oci.OrasClientLib.get_manifest",
            return_value={"schemaVersion": 2},
        )
        mock_get_container = mocker.MagicMock()
        mock_container = mocker.MagicMock()
        mock_get_container.return_value = mock_container
        mocker.patch.object(OrasClient, "get_container", mock_get_container)

        client = OrasClient()
        result = client.get_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        assert result == {"schemaVersion": 2}
        mock_get_container.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        # Should pass Container object, not string, to base class
        mock_base_get_manifest.assert_called_once_with(
            mock_container,
            None,
            None,
        )

    def test_get_manifest_with_container_object_and_allowed_media_type(self, mocker: Any) -> None:
        """get_manifest(Container, allowed_media_type=[...]) should pass through unchanged to base."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_base_get_manifest = mocker.patch(
            "margot.infra.oci.OrasClientLib.get_manifest",
            return_value={"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json"},
        )

        container = Container(name="g2n4p2m7/margo", registry="public.ecr.aws")
        allowed_types = ["application/vnd.oci.image.manifest.v1+json"]

        client = OrasClient()
        result = client.get_manifest(container, allowed_media_type=allowed_types)

        assert result == {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json"}
        # Should pass Container and allowed_media_type through unchanged to base class
        mock_base_get_manifest.assert_called_once_with(
            container,
            allowed_types,
            None,
        )

    def test_get_manifest_with_container_and_validation_schema(self, mocker: Any) -> None:
        """get_manifest(Container, validation_schema=...) should pass all params through."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mock_base_get_manifest = mocker.patch(
            "margot.infra.oci.OrasClientLib.get_manifest",
            return_value={"schemaVersion": 2},
        )

        container = Container(name="g2n4p2m7/margo", registry="public.ecr.aws")
        validation_schema = {"type": "object"}

        client = OrasClient()
        result = client.get_manifest(container, validation_schema=validation_schema)

        assert result == {"schemaVersion": 2}
        mock_base_get_manifest.assert_called_once_with(
            container,
            None,
            validation_schema,
        )

    def test_pull_invokes_get_manifest_polymorphically_with_container_and_media_type(
        self, mocker: Any
    ) -> None:
        """pull() → super().pull() → internal self.get_manifest(container, allowed_media_type).

        This is the actual scenario that was broken: oras.provider.Registry.pull() internally
        calls self.get_manifest(container, allowed_media_type) polymorphically. Our override
        must accept both parameters to avoid TypeError.
        """
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)

        # Mock the base class's pull() to call our get_manifest with Container + allowed_media_type
        # This simulates what oras.provider.Registry.pull() does internally
        original_get_manifest_called = []

        def mock_pull_impl(self, **kwargs) -> list[str]:  # noqa: ARG001
            # Simulate what oras.provider.Registry.pull() does internally
            container = Container(name="g2n4p2m7/margo", registry="public.ecr.aws")
            allowed_types = ["application/vnd.oci.image.manifest.v1+json"]
            # This internal call should work without TypeError
            # Call the real get_manifest implementation (not base), which should accept all params
            self.get_manifest(container, allowed_media_type=allowed_types)
            original_get_manifest_called.append((container, allowed_types))
            return ["margo.yaml"]

        mocker.patch("margot.infra.oci.OrasClientLib.pull", mock_pull_impl)
        # Mock the base get_manifest to avoid actually hitting the network
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest", return_value={})

        client = OrasClient()
        # This should NOT raise TypeError about positional arguments
        result = client.pull("public.ecr.aws/g2n4p2m7/margo:1.0.0", "/tmp/out")

        assert result == ["margo.yaml"]
        # Verify that our override was called with Container (not string)
        assert len(original_get_manifest_called) == 1

    def test_get_manifest_logging_with_string_uri(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """get_manifest(uri_string) should log the URI string in debug output."""
        console.set_debug(True)
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest", return_value={})
        mock_container = mocker.MagicMock()
        mocker.patch.object(OrasClient, "get_container", return_value=mock_container)
        _out, err = capture_console

        client = OrasClient()
        client.get_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        err_output = err.getvalue()
        assert "GET manifest:" in err_output
        # Should log the URI or container ref
        assert "public.ecr.aws/g2n4p2m7/margo:1.0.0" in err_output or "g2n4p2m7/margo" in err_output

    def test_get_manifest_logging_with_container_object(
        self, mocker: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """get_manifest(Container) should log the container in debug output without errors."""
        console.set_debug(True)
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest", return_value={})

        container = Container(name="g2n4p2m7/margo", registry="public.ecr.aws")
        _out, err = capture_console

        client = OrasClient()
        client.get_manifest(container)

        err_output = err.getvalue()
        assert "GET manifest:" in err_output
