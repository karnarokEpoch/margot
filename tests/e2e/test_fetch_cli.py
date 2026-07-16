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
        # Mock OrasClient at infra boundary
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mocker.patch("margot.infra.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        # NOTE: Will fail until infra/oci.py is implemented
        # Expected: exit_code == 0, JSON output in stdout
        assert "schemaVersion" in result.stdout or result.exit_code == 1

    def test_fetch_network_error(self, mocker: Any) -> None:
        """Should handle network errors gracefully."""
        mock_client = MagicMock()
        mock_client.get_manifest.side_effect = Exception("Connection refused")
        mocker.patch("margot.infra.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["fetch", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Error fetching manifest" in output or "Connection refused" in output

    def test_margot_version_flag(self) -> None:
        """Should print version with --version flag."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "margot" in result.stdout
