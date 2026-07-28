"""Integration tests for services/auth.py."""

import base64
from datetime import UTC, datetime
from io import StringIO
import json
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

    def test_login_with_expiry_hours_calls_save_expiry(self, mocker: Any) -> None:
        """Should call save_expiry in credentials when expiry_hours is provided."""
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mock_save = mocker.patch("margot.services.auth.creds_infra.save_expiry")

        result = auth.login(
            registry="public.ecr.aws",
            username="AWS",
            password="token123",
            expiry_hours=12,
        )

        assert result is not None
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][0] == "public.ecr.aws"
        # Second arg is the datetime — just check it's set
        assert call_args[0][1] is not None

    def test_login_without_expiry_hours_does_not_call_save_expiry(self, mocker: Any) -> None:
        """Should NOT call save_expiry when expiry_hours is None."""
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mock_save = mocker.patch("margot.services.auth.creds_infra.save_expiry")

        result = auth.login(registry="public.ecr.aws", username="AWS", password="token123")

        assert result is None
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

    def test_login_auto_detects_expiry_from_ecr_token(self, mocker: Any) -> None:
        """Should auto-detect expiry from ECR token when expiry_hours is None."""
        expiration_ts = 1785291060
        token = base64.b64encode(json.dumps({"expiration": expiration_ts}).encode()).decode()

        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mock_save = mocker.patch("margot.services.auth.creds_infra.save_expiry")

        result = auth.login(registry="public.ecr.aws", username="AWS", password=token)

        assert result == datetime.fromtimestamp(expiration_ts, tz=UTC)
        mock_save.assert_called_once()
        saved_registry, saved_expiry = mock_save.call_args[0]
        assert saved_registry == "public.ecr.aws"
        assert saved_expiry == datetime.fromtimestamp(expiration_ts, tz=UTC)

    def test_login_explicit_expiry_hours_wins_over_auto_detected(self, mocker: Any) -> None:
        """--expiry-hours should take precedence over auto-detected expiry from token."""
        expiration_ts = 1785291060
        token = base64.b64encode(json.dumps({"expiration": expiration_ts}).encode()).decode()

        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mock_save = mocker.patch("margot.services.auth.creds_infra.save_expiry")

        auth.login(registry="public.ecr.aws", username="AWS", password=token, expiry_hours=6)

        mock_save.assert_called_once()
        saved_registry, saved_expiry = mock_save.call_args[0]
        assert saved_registry == "public.ecr.aws"
        # Should NOT be the token expiry — should be ~6h from now
        assert saved_expiry != datetime.fromtimestamp(expiration_ts, tz=UTC)

    def test_login_no_expiry_saved_when_token_not_parseable(self, mocker: Any) -> None:
        """Should not save expiry when password is not a parseable ECR token."""
        mock_client = MagicMock()
        mocker.patch("margot.services.auth.oci.OrasClient", return_value=mock_client)
        mock_save = mocker.patch("margot.services.auth.creds_infra.save_expiry")

        result = auth.login(registry="public.ecr.aws", username="AWS", password="plainpassword")

        assert result is None
        mock_save.assert_not_called()


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
