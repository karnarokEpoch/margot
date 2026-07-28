"""E2E tests for auth command via CLI."""

from datetime import UTC, datetime
from typing import Any

from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()


class TestAuthCLI:
    """E2E tests for margot auth commands."""

    def test_auth_help(self) -> None:
        """Should display auth subcommand help with login/logout."""
        result = runner.invoke(app, ["auth", "--help"])

        assert result.exit_code == 0
        assert "login" in result.stdout
        assert "logout" in result.stdout

    def test_auth_login_help(self) -> None:
        """Should display login command help."""
        result = runner.invoke(app, ["auth", "login", "--help"])

        assert result.exit_code == 0
        assert "Login to an OCI registry" in result.stdout
        assert "registry" in result.stdout.lower()
        assert "username" in result.stdout
        assert "password" in result.stdout
        assert "expiry" in result.stdout

    def test_auth_login_success(self, mocker: Any) -> None:
        """Should call service.login with correct args and exit 0."""
        mock_login = mocker.patch("margot.commands.auth.auth_service.login", return_value=None)

        result = runner.invoke(
            app,
            ["auth", "login", "public.ecr.aws", "--username", "AWS", "--password-stdin"],
            input="mytoken\n",
        )

        assert result.exit_code == 0
        mock_login.assert_called_once_with(
            registry="public.ecr.aws",
            username="AWS",
            password="mytoken",
            expiry_hours=None,
        )
        assert "Logged in to public.ecr.aws" in result.stdout

    def test_auth_login_without_password_stdin_exits_1(self) -> None:
        """Should exit 1 with error about password required."""
        result = runner.invoke(
            app,
            ["auth", "login", "public.ecr.aws", "--username", "AWS"],
        )

        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "Password required" in output

    def test_auth_login_without_username_exits_1(self) -> None:
        """Should exit 1 with error about username required."""
        result = runner.invoke(
            app,
            ["auth", "login", "public.ecr.aws", "--password-stdin"],
            input="mytoken\n",
        )

        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "Username required" in output

    def test_auth_logout_success(self, mocker: Any) -> None:
        """Should call service.logout with correct args and exit 0."""
        mock_logout = mocker.patch("margot.commands.auth.auth_service.logout")

        result = runner.invoke(
            app,
            ["auth", "logout", "public.ecr.aws"],
        )

        assert result.exit_code == 0
        mock_logout.assert_called_once_with(registry="public.ecr.aws")
        assert "Logged out from public.ecr.aws" in result.stdout

    def test_auth_login_with_expiry_hours(self, mocker: Any) -> None:
        """Should pass expiry_hours=12 to service when --expiry-hours 12 is set."""
        mock_login = mocker.patch("margot.commands.auth.auth_service.login")

        result = runner.invoke(
            app,
            [
                "auth",
                "login",
                "public.ecr.aws",
                "--username",
                "AWS",
                "--password-stdin",
                "--expiry-hours",
                "12",
            ],
            input="mytoken\n",
        )

        assert result.exit_code == 0
        mock_login.assert_called_once_with(
            registry="public.ecr.aws",
            username="AWS",
            password="mytoken",
            expiry_hours=12,
        )

    def test_auth_login_service_raises_exits_1(self, mocker: Any) -> None:
        """Should exit 1 with error message when service raises."""
        mocker.patch(
            "margot.commands.auth.auth_service.login",
            side_effect=Exception("401 Unauthorized"),
        )

        result = runner.invoke(
            app,
            ["auth", "login", "public.ecr.aws", "--username", "AWS", "--password-stdin"],
            input="mytoken\n",
        )

        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "Login failed" in output

    def test_auth_login_displays_expiry_when_detected(self, mocker: Any) -> None:
        """Should display time-until-expiry line when service returns an expiry datetime."""
        expires_at = datetime(2099, 1, 1, 12, 0, 0, tzinfo=UTC)
        mocker.patch("margot.commands.auth.auth_service.login", return_value=expires_at)

        result = runner.invoke(
            app,
            ["auth", "login", "public.ecr.aws", "--username", "AWS", "--password-stdin"],
            input="mytoken\n",
        )

        assert result.exit_code == 0
        assert "Logged in to public.ecr.aws" in result.stdout
        assert "expires" in result.stdout.lower()
