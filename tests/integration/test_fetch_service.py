"""Integration tests for services/fetch.py."""

from io import StringIO
from typing import Any
from unittest.mock import MagicMock

from pytest import raises

from margot import console
from margot.infra.credentials import CredentialsExpiredError
from margot.services import fetch


class TestFetchService:
    """Tests for fetch_manifest() service."""

    def test_fetch_manifest_calls_oras_client(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """Should call OrasClient.get_manifest with the URI."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.credentials.check_credentials")
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        mock_client.get_manifest.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        assert result == mock_manifest

    def test_fetch_manifest_propagates_exception(self, mocker: Any) -> None:
        """Should propagate exceptions from OrasClient."""
        mock_client = MagicMock()
        mock_client.get_manifest.side_effect = Exception("Registry error")
        mocker.patch("margot.services.fetch.credentials.check_credentials")
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        with raises(Exception, match="Registry error"):
            fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

    def test_fetch_manifest_returns_manifest(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """Should return the manifest dict from OrasClient."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.credentials.check_credentials")
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        assert isinstance(result, dict)
        assert "schemaVersion" in result

    def test_fetch_manifest_raises_on_empty_uri(self) -> None:
        """Should raise ValueError when URI is empty."""
        with raises(ValueError, match="URI must not be empty"):
            fetch.fetch_manifest("")

    def test_fetch_manifest_raises_on_missing_tag_separator(self) -> None:
        """Should raise ValueError when URI has no colon (missing tag separator)."""
        with raises(ValueError, match="URI must contain a tag"):
            fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo")

    def test_fetch_manifest_raises_on_empty_tag(self) -> None:
        """Should raise ValueError when tag after colon is empty."""
        with raises(ValueError, match="URI must contain a tag"):
            fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:")


class TestFetchServiceVerbose:
    """Tests for fetch_manifest() with verbose output."""

    def test_fetch_emits_info_when_verbose(
        self, mocker: Any, mock_manifest: dict[str, Any], capture_console: tuple[StringIO, StringIO], reset_console: None
    ) -> None:
        """fetch_manifest() should emit info messages on stderr when verbose=True."""
        console.set_verbose(True)
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.credentials.check_credentials")
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)
        out, err = capture_console
        fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        err_text = err.getvalue()
        assert "Fetching manifest for:" in err_text
        assert "Manifest retrieved." in err_text
        assert out.getvalue() == ""

    def test_fetch_no_info_without_verbose(
        self, mocker: Any, mock_manifest: dict[str, Any], capture_console: tuple[StringIO, StringIO], reset_console: None
    ) -> None:
        """fetch_manifest() should emit no info messages when verbose=False."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.credentials.check_credentials")
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)
        out, err = capture_console
        fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        assert err.getvalue() == ""
        assert out.getvalue() == ""


class TestFetchServiceAuth:
    """Tests for authenticated fetch_manifest(): hostname extraction, credential checks."""

    def test_fetch_manifest_checks_credentials_for_hostname(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """Should call check_credentials with the hostname extracted from the URI."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mock_check_credentials = mocker.patch("margot.services.fetch.credentials.check_credentials")
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        mock_check_credentials.assert_called_once_with("public.ecr.aws")

    def test_fetch_manifest_passes_hostname_to_oras_client(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """Should construct OrasClient with hostname=<extracted hostname>."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.credentials.check_credentials")
        mock_oras_client_cls = mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        mock_oras_client_cls.assert_called_once_with(hostname="public.ecr.aws")

    def test_fetch_manifest_expired_credentials_propagates(self, mocker: Any) -> None:
        """Should propagate CredentialsExpiredError raised by check_credentials before constructing a client."""
        mock_oras_client_cls = mocker.patch("margot.services.fetch.oci.OrasClient")
        mocker.patch(
            "margot.services.fetch.credentials.check_credentials",
            side_effect=CredentialsExpiredError("Credentials for public.ecr.aws have expired."),
        )

        with raises(CredentialsExpiredError, match="expired"):
            fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        mock_oras_client_cls.assert_not_called()

    def test_fetch_manifest_near_expiry_warns_but_proceeds(
        self, mocker: Any, mock_manifest: dict[str, Any], capture_console: tuple[StringIO, StringIO], reset_console: None
    ) -> None:
        """Near-expiry credentials should emit a console.warning but still fetch and return the manifest."""

        def _warn_and_proceed(_registry: str) -> None:
            console.warning("Credentials for public.ecr.aws expire in less than 5 minutes.")

        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.credentials.check_credentials", side_effect=_warn_and_proceed)
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)
        _out, err = capture_console

        result = fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        assert "warning" in err.getvalue().lower()
        assert "expire in less than" in err.getvalue()
        assert "minutes" in err.getvalue()
        assert result == mock_manifest
        mock_client.get_manifest.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0")

    def test_fetch_manifest_no_tracked_credentials_proceeds_anonymously(
        self, mocker: Any, mock_manifest: dict[str, Any]
    ) -> None:
        """When no credentials are tracked for the registry, check_credentials is a no-op and fetch proceeds."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        # check_credentials with no tracked expiry returns None silently (real behavior, not mocked away)
        mocker.patch("margot.services.fetch.credentials.load_expiry", return_value=None)
        mock_oras_client_cls = mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = fetch.fetch_manifest("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        mock_oras_client_cls.assert_called_once_with(hostname="public.ecr.aws")
        mock_client.get_manifest.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        assert result == mock_manifest
