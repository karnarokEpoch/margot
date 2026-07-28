"""Integration tests for services/auth.py."""

from io import StringIO
from typing import Any
from unittest.mock import MagicMock

from pytest import raises

from margot import console
from margot.services import auth


class TestLoginService:
    """Tests for auth.login() service."""

    def test_login_calls_oras_client_login(self, mocker: Any) -> None:
        """Should call OrasClient.login() with correct arguments."""
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.auth.creds_infra.save_expiry")

        auth.login(registry="public.ecr.aws", username="AWS", password="token123")

        mock_client.login.assert_called_once_with(hostname="public.ecr.aws", username="AWS", password="token123")

    def test_login_with_save_expiry_calls_save_expiry(self, mocker: Any) -> None:
        """Should call save_expiry in credentials when save_expiry=True."""
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mock_save = mocker.patch("margot.services.auth.creds_infra.save_expiry")

        auth.login(
            registry="public.ecr.aws",
            username="AWS",
            password="token123",
            save_expiry=True,
        )

        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][0] == "public.ecr.aws"
        # Second arg is the datetime — just check it's set
        assert call_args[0][1] is not None

    def test_login_without_save_expiry_does_not_call_save_expiry(self, mocker: Any) -> None:
        """Should NOT call save_expiry when save_expiry=False."""
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mock_save = mocker.patch("margot.services.auth.creds_infra.save_expiry")

        auth.login(registry="public.ecr.aws", username="AWS", password="token123")

        mock_save.assert_not_called()

    def test_login_emits_info_message(self, mocker: Any, capture_console: tuple[StringIO, StringIO], reset_console: None) -> None:
        """Should emit info messages via console."""
        console.set_verbose(True)
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.auth.creds_infra.save_expiry")

        _out, err = capture_console
        auth.login(registry="public.ecr.aws", username="AWS", password="token123")

        err_text = err.getvalue()
        assert "Logging in to public.ecr.aws" in err_text

    def test_login_propagates_exception_from_oras_client(self, mocker: Any) -> None:
        """Should propagate exceptions from OrasClient (auth failure)."""
        mock_client = MagicMock()
        mock_client.login.side_effect = Exception("401 Unauthorized")
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)

        with raises(Exception, match="401 Unauthorized"):
            auth.login(registry="public.ecr.aws", username="AWS", password="badtoken")


class TestLogoutService:
    """Tests for auth.logout() service."""

    def test_logout_calls_oras_client_logout(self, mocker: Any) -> None:
        """Should call OrasClient.logout() with correct args."""
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.auth.creds_infra.remove_expiry")

        auth.logout(registry="public.ecr.aws")

        mock_client.logout.assert_called_once_with(hostname="public.ecr.aws")

    def test_logout_calls_remove_expiry(self, mocker: Any) -> None:
        """Should call remove_expiry on credentials."""
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mock_remove = mocker.patch("margot.services.auth.creds_infra.remove_expiry")

        auth.logout(registry="public.ecr.aws")

        mock_remove.assert_called_once_with("public.ecr.aws")

    def test_logout_emits_info_message(
        self, mocker: Any, capture_console: tuple[StringIO, StringIO], reset_console: None
    ) -> None:
        """Should emit info messages via console."""
        console.set_verbose(True)
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.auth.creds_infra.remove_expiry")

        _out, err = capture_console
        auth.logout(registry="public.ecr.aws")

        err_text = err.getvalue()
        assert "Logging out from public.ecr.aws" in err_text
