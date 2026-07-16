"""E2E tests for pull command via CLI."""

import re
from typing import Any
from unittest.mock import MagicMock

from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


def _make_margo_manifest() -> dict[str, Any]:
    """Return a minimal margo OCI manifest for testing."""
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.margo.app.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "size": 2,
        },
        "layers": [
            {
                "mediaType": "application/vnd.margo.app.description.v1+yaml",
                "digest": "sha256:def456",
                "annotations": {"org.opencontainers.image.title": "margo.yaml"},
            }
        ],
    }


class TestPullCLI:
    """E2E tests for margot pull command."""

    def test_pull_help(self) -> None:
        """Should display pull command help with expected text."""
        result = runner.invoke(app, ["pull", "--help"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "Pull OCI artifact" in plain
        assert "URI" in plain
        assert "--output" in plain

    def test_pull_missing_uri(self) -> None:
        """Should fail with a non-zero exit code when URI is omitted."""
        result = runner.invoke(app, ["pull"])

        assert result.exit_code != 0
        output = _strip_ansi(result.stdout + (result.stderr or ""))
        assert "Missing argument" in output or "required" in output.lower()

    def test_pull_success(self, mocker: Any, tmp_path: Any) -> None:
        """Should report pulled paths and exit 0 on success."""
        pulled_file = str(tmp_path / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert pulled_file in plain

    def test_pull_uses_output_flag(self, mocker: Any, tmp_path: Any) -> None:
        """Should pass --output directory to the pull service."""
        outdir = str(tmp_path / "out")
        pulled_file = str(tmp_path / "out" / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0", "--output", outdir])

        assert result.exit_code == 0
        mock_client.pull.assert_called_once_with(uri="public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=outdir)

    def test_pull_client_error_exits_1(self, mocker: Any) -> None:
        """Should exit 1 and show error message when client.pull raises."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.side_effect = Exception("Registry unavailable")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "Error pulling artifact" in plain

    def test_pull_empty_uri_exits_1(self) -> None:
        """Should exit 1 when an empty URI is provided."""
        result = runner.invoke(app, ["pull", ""])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "Error" in plain
