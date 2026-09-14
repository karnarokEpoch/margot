"""E2E tests for package command via CLI."""

import re
from typing import Any

from typer.testing import CliRunner

from margot.domain.models import PackageType
from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


class TestPackageCLIHelp:
    """Help text and syntax tests for package command."""

    def test_package_help(self) -> None:
        """Should display package command help."""
        result = runner.invoke(app, ["package", "--help"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "bundle" in plain.lower()

    def test_package_help_short_flag(self) -> None:
        """Should display package help with -h shortcut."""
        result = runner.invoke(app, ["package", "-h"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "bundle" in plain.lower() or "package" in plain.lower()


class TestPackageTypeValidation:
    """CLI-level type validation tests for package command."""

    def test_package_invalid_type_exits_1(self, mocker: Any) -> None:
        """Should exit 1 with error for invalid --type."""
        # Mock the service to avoid needing real build artifacts
        mocker.patch("margot.commands.package.package_service.package")

        result = runner.invoke(
            app,
            ["package", "--type", "invalid"],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "invalid" in plain.lower()

    def test_package_bundle_with_margo_exits_1(self, mocker: Any) -> None:
        """Should exit 1 when --type bundle is combined with --type margo."""
        mocker.patch("margot.commands.package.package_service.package")

        result = runner.invoke(
            app,
            ["package", "--type", "bundle", "--type", "margo"],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "bundle" in plain.lower()

    def test_package_multiple_types_exits_1(self, mocker: Any) -> None:
        """Should exit 1 when multiple non-bundle types are specified."""
        mocker.patch("margot.commands.package.package_service.package")

        result = runner.invoke(
            app,
            ["package", "--type", "margo", "--type", "compose"],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "multiple" in plain.lower()


class TestPackageSuccessPath:
    """Tests for successful package command execution."""

    def test_package_success_calls_service(self, mocker: Any) -> None:
        """Should call service.package with correct parameters on success."""
        mock_package = mocker.patch(
            "margot.commands.package.package_service.package",
            return_value="/tmp/bundle.tgz",
        )

        result = runner.invoke(
            app,
            ["package", "--type", "margo"],
        )

        assert result.exit_code == 0
        mock_package.assert_called_once()

    def test_package_no_type_defaults_to_bundle(self, mocker: Any) -> None:
        """Should default to BUNDLE when --type is omitted."""
        mock_package = mocker.patch(
            "margot.commands.package.package_service.package",
            return_value="/tmp/bundle.tgz",
        )

        result = runner.invoke(app, ["package"])

        assert result.exit_code == 0

        # Check that service was called with BUNDLE type
        call_args = mock_package.call_args
        assert call_args[0][0] == PackageType.BUNDLE

    def test_package_with_no_images_flag(self, mocker: Any) -> None:
        """Should pass include_images=False when --no-images is set."""
        mock_package = mocker.patch(
            "margot.commands.package.package_service.package",
            return_value="/tmp/bundle.tgz",
        )

        result = runner.invoke(app, ["package", "--no-images"])

        assert result.exit_code == 0

        # Check that include_images=False was passed
        call_kwargs = mock_package.call_args[1]
        assert call_kwargs.get("include_images") is False


class TestPackageServiceError:
    """Tests for service-layer error handling."""

    def test_package_value_error_exits_1(self, mocker: Any) -> None:
        """Should exit 1 when service raises ValueError."""
        mocker.patch(
            "margot.commands.package.package_service.package",
            side_effect=ValueError("Build output not found"),
        )

        result = runner.invoke(app, ["package", "--type", "margo"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "Build output not found" in plain
