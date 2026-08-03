"""Integration tests for services/auth.py."""

import base64
from datetime import UTC, datetime, timedelta
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


class TestAuthStatusService:
    """Tests for auth.auth_status() service."""

    def test_returns_empty_result_when_nothing_tracked(self, mocker: Any) -> None:
        """Should return empty tracked and oras_only lists when both sources are empty."""
        mocker.patch("margot.services.auth.creds_infra.list_tracked", return_value=[])
        mocker.patch("margot.services.auth.creds_infra.list_oras_registries", return_value=[])

        result = auth.auth_status()

        assert result.tracked == []
        assert result.oras_only == []

    def test_tracked_only_classifies_each_entry(self, mocker: Any) -> None:
        """Should classify each tracked registry's status correctly."""
        now = datetime.now(tz=UTC)
        valid_expiry = now + timedelta(hours=6)
        expiring_expiry = now + timedelta(minutes=2)
        expired_expiry = now - timedelta(hours=1)

        mocker.patch(
            "margot.services.auth.creds_infra.list_tracked",
            return_value=[
                ("valid.registry.io", valid_expiry),
                ("expiring.registry.io", expiring_expiry),
                ("expired.registry.io", expired_expiry),
            ],
        )
        mocker.patch("margot.services.auth.creds_infra.list_oras_registries", return_value=[])

        result = auth.auth_status()

        statuses = {t.hostname: t.status for t in result.tracked}
        assert statuses == {
            "valid.registry.io": "VALID",
            "expiring.registry.io": "EXPIRING",
            "expired.registry.io": "EXPIRED",
        }
        assert result.oras_only == []

    def test_oras_only_when_no_tracked_entries(self, mocker: Any) -> None:
        """Should list oras-only registries when nothing is tracked."""
        mocker.patch("margot.services.auth.creds_infra.list_tracked", return_value=[])
        mocker.patch(
            "margot.services.auth.creds_infra.list_oras_registries",
            return_value=["untracked.registry.io"],
        )

        result = auth.auth_status()

        assert result.tracked == []
        assert result.oras_only == ["untracked.registry.io"]

    def test_overlap_registry_appears_only_in_tracked(self, mocker: Any) -> None:
        """A registry present in both lists must appear only once, in tracked."""
        now = datetime.now(tz=UTC)
        expiry = now + timedelta(hours=1)

        mocker.patch(
            "margot.services.auth.creds_infra.list_tracked",
            return_value=[("public.ecr.aws", expiry)],
        )
        mocker.patch(
            "margot.services.auth.creds_infra.list_oras_registries",
            return_value=["public.ecr.aws", "other.registry.io"],
        )

        result = auth.auth_status()

        assert [t.hostname for t in result.tracked] == ["public.ecr.aws"]
        assert result.oras_only == ["other.registry.io"]

    def test_emits_info_messages(self, mocker: Any, capture_console: tuple[StringIO, StringIO], reset_console: None) -> None:
        """Should emit info messages via console at start and completion."""
        console.set_verbose(True)
        mocker.patch("margot.services.auth.creds_infra.list_tracked", return_value=[])
        mocker.patch("margot.services.auth.creds_infra.list_oras_registries", return_value=[])

        _out, err = capture_console
        auth.auth_status()

        err_text = err.getvalue()
        assert "info:" in err_text
