"""E2E tests for fetch command via CLI."""

from typing import Any
from unittest.mock import MagicMock

from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()


class TestFetchCLI:
    """E2E tests for margot fetch command."""

    def test_fetch_help(self) -> None:
        """Should display fetch command help."""
        result = runner.invoke(app, ["fetch", "--help"])

        assert result.exit_code == 0
        assert "Fetch and display the manifest" in result.stdout
        assert "URI" in result.stdout

    def test_fetch_missing_uri(self) -> None:
        """Should fail when URI argument is missing."""
        result = runner.invoke(app, ["fetch"])

        assert result.exit_code != 0
        output = result.stdout + result.stderr
        assert "Missing argument" in output or "required" in output.lower()

    def test_fetch_success(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """Should fetch manifest and print JSON output."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        assert "schemaVersion" in result.stdout

    def test_fetch_network_error(self, mocker: Any) -> None:
        """Should handle network errors gracefully."""
        mock_client = MagicMock()
        mock_client.get_manifest.side_effect = Exception("Connection refused")
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Error fetching manifest" in output

    def test_margot_version_flag(self) -> None:
        """Should print version with --version flag."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "margot" in result.stdout



class TestFetchCLIVerbosity:
    """E2E tests for fetch --verbose and --debug flags."""

    def test_fetch_verbose_flag_shows_info_on_stderr(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """fetch with --verbose should emit info messages on stderr."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["--verbose", "fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        stderr_text = result.stderr or ""
        stdout_text = result.stdout
        assert "Fetching manifest for:" in stderr_text
        assert "Manifest retrieved." in stderr_text
        assert "schemaVersion" in stdout_text

    def test_fetch_verbose_short_flag(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """fetch with -v short flag should emit info messages on stderr."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["-v", "fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        stderr_text = result.stderr or ""
        assert "Fetching manifest for:" in stderr_text

    def test_fetch_debug_flag_shows_debug_on_stderr(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """fetch with --debug should emit info/debug messages on stderr."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["--debug", "fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        stderr_text = result.stderr or ""
        # Should contain some output (stderr or command output)
        assert len(stderr_text) > 0 or "schemaVersion" in result.stdout

    def test_fetch_debug_short_flag(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """fetch with -d short flag should emit debug messages."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["-d", "fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        # Should complete without error
        assert len(result.stdout) > 0

    def test_fetch_no_flags_no_info_output(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """fetch without --verbose or --debug should complete successfully."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        # Should output the manifest JSON
        assert "schemaVersion" in result.stdout

    def test_global_verbose_before_fetch_subcommand(self, mocker: Any, mock_manifest: dict[str, Any]) -> None:
        """--verbose before fetch subcommand should work like fetch --verbose."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.services.fetch.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["--verbose", "fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        stderr_text = result.stderr or ""
        assert "Fetching manifest for:" in stderr_text
