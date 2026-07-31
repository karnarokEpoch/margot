"""E2E tests for push command via CLI."""

import re
from typing import Any

from typer.testing import CliRunner

from margot.domain.models import BuildTarget, PackageType
from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


class TestPushHelp:
    """E2E tests for push help output."""

    def test_push_help_shows_flags(self) -> None:
        """Should display push command help with expected flags."""
        result = runner.invoke(app, ["push", "--help"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "Push built Margo" in plain
        assert "--type" in plain
        assert "--registry" in plain
        assert "--repository" in plain
        assert "--build-dir" in plain
        assert "--variant" in plain

    def test_push_help_short_flag(self) -> None:
        """Should display push help with -h shortcut."""
        result = runner.invoke(app, ["push", "-h"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "Push built Margo" in plain


class TestPushCLI:
    """E2E tests for margot push command."""

    def test_push_no_flags_calls_service_with_all(self, mocker: Any) -> None:
        """Should call push service with PackageType for each type (expanded from all) and defaults."""
        mock_push = mocker.patch(
            "margot.commands.push.push_service.push",
            return_value=[
                BuildTarget(
                    package_type=PackageType.MARGO,
                    variant_name=None,
                    version="1.0.0",
                    source_dir=".",
                    output_dir=".dist/1.0.0/margo",
                ),
            ],
        )

        result = runner.invoke(app, ["push"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "Pushed: 1.0.0" in plain
        # Should be called for each expanded type (margo, compose, quadlet)
        assert mock_push.call_count == 3

    def test_push_type_margo_calls_service_with_margo(self, mocker: Any) -> None:
        """Should call push service with PackageType.MARGO."""
        mock_push = mocker.patch(
            "margot.commands.push.push_service.push",
            return_value=[
                BuildTarget(
                    package_type=PackageType.MARGO,
                    variant_name=None,
                    version="1.0.0",
                    source_dir=".",
                    output_dir=".dist/1.0.0/margo",
                ),
            ],
        )

        result = runner.invoke(app, ["push", "--type", "margo"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "Pushed: 1.0.0" in plain
        mock_push.assert_called_once_with(
            PackageType.MARGO,
            project_dir=".",
            build_dir=".dist",
            registry=None,
            repository=None,
            variant=None,
        )

    def test_push_type_compose_with_variant(self, mocker: Any) -> None:
        """Should call push service with PackageType.COMPOSE and variant."""
        mock_push = mocker.patch(
            "margot.commands.push.push_service.push",
            return_value=[
                BuildTarget(
                    package_type=PackageType.COMPOSE,
                    variant_name="simple",
                    version="1.0.0_simple",
                    source_dir=".",
                    output_dir=".dist/1.0.0_simple",
                ),
            ],
        )

        result = runner.invoke(app, ["push", "--type", "compose", "--variant", "simple"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "Pushed (simple): 1.0.0_simple" in plain
        mock_push.assert_called_once_with(
            PackageType.COMPOSE,
            project_dir=".",
            build_dir=".dist",
            registry=None,
            repository=None,
            variant="simple",
        )

    def test_push_with_registry_and_repository(self, mocker: Any) -> None:
        """Should pass registry and repository to service."""
        mock_push = mocker.patch(
            "margot.commands.push.push_service.push",
            return_value=[
                BuildTarget(
                    package_type=PackageType.MARGO,
                    variant_name=None,
                    version="1.0.0",
                    source_dir=".",
                    output_dir=".dist/1.0.0/margo",
                ),
            ],
        )

        result = runner.invoke(
            app, ["push", "--type", "margo", "--registry", "public.ecr.aws", "--repository", "org/repo"]
        )

        assert result.exit_code == 0
        mock_push.assert_called_once_with(
            PackageType.MARGO,
            project_dir=".",
            build_dir=".dist",
            registry="public.ecr.aws",
            repository="org/repo",
            variant=None,
        )

    def test_push_service_value_error_exits_1(self, mocker: Any) -> None:
        """Should exit 1 with error message when service raises ValueError."""
        mocker.patch(
            "margot.commands.push.push_service.push",
            side_effect=ValueError("margo component not defined in margo.yaml"),
        )

        result = runner.invoke(app, ["push", "--type", "margo"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "margo component not defined" in plain

    def test_push_service_exception_exits_1(self, mocker: Any) -> None:
        """Should exit 1 with 'Push failed' when service raises unexpected exception."""
        mocker.patch(
            "margot.commands.push.push_service.push",
            side_effect=RuntimeError("network timeout"),
        )

        result = runner.invoke(app, ["push", "--type", "margo"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "Push failed" in plain

    def test_push_nothing_pushed_shows_warning(self, mocker: Any) -> None:
        """Should show warning when nothing was pushed."""
        mocker.patch("margot.commands.push.push_service.push", return_value=[])

        result = runner.invoke(app, ["push", "--type", "margo"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "Nothing was pushed" in plain

    def test_push_invalid_type_exits_1(self) -> None:
        """Should exit 1 with error message for invalid --type."""
        result = runner.invoke(app, ["push", "--type", "invalid"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "invalid --type" in plain
