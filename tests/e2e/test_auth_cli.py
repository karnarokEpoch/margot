"""E2E tests for auth command via CLI."""

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
        assert "registry" in result.stdout
        assert "username" in result.stdout
        assert "password" in result.stdout
        assert "save" in result.stdout

    def test_auth_login_success(self, mocker: Any) -> None:
        """Should call service.login with correct args and exit 0."""
        mock_login = mocker.patch("margot.commands.auth.auth_service.login")

        result = runner.invoke(
            app,
            ["auth", "login", "--registry", "public.ecr.aws", "--username", "AWS", "--password-stdin"],
            input="mytoken\n",
        )

        assert result.exit_code == 0
        mock_login.assert_called_once_with(
            registry="public.ecr.aws",
            username="AWS",
            password="mytoken",
            save_expiry=False,
        )
        assert "Logged in to public.ecr.aws" in result.stdout

    def test_auth_login_without_password_stdin_exits_1(self) -> None:
        """Should exit 1 with error about password required."""
        result = runner.invoke(
            app,
            ["auth", "login", "--registry", "public.ecr.aws", "--username", "AWS"],
        )

        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "Password required" in output

    def test_auth_login_without_username_exits_1(self) -> None:
        """Should exit 1 with error about username required."""
        result = runner.invoke(
            app,
            ["auth", "login", "--registry", "public.ecr.aws", "--password-stdin"],
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
            ["auth", "logout", "--registry", "public.ecr.aws"],
        )

        assert result.exit_code == 0
        mock_logout.assert_called_once_with(registry="public.ecr.aws")
        assert "Logged out from public.ecr.aws" in result.stdout

    def test_auth_login_with_save_expiry(self, mocker: Any) -> None:
        """Should pass save_expiry=True to service when --save-expiry is set."""
        mock_login = mocker.patch("margot.commands.auth.auth_service.login")

        result = runner.invoke(
            app,
            [
                "auth",
                "login",
                "--registry",
                "public.ecr.aws",
                "--username",
                "AWS",
                "--password-stdin",
                "--save-expiry",
            ],
            input="mytoken\n",
        )

        assert result.exit_code == 0
        mock_login.assert_called_once_with(
            registry="public.ecr.aws",
            username="AWS",
            password="mytoken",
            save_expiry=True,
        )

    def test_auth_login_service_raises_exits_1(self, mocker: Any) -> None:
        """Should exit 1 with error message when service raises."""
        mocker.patch(
            "margot.commands.auth.auth_service.login",
            side_effect=Exception("401 Unauthorized"),
        )

        result = runner.invoke(
            app,
            ["auth", "login", "--registry", "public.ecr.aws", "--username", "AWS", "--password-stdin"],
            input="mytoken\n",
        )

        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "Login failed" in output
