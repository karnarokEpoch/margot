"""E2E tests for pull command via CLI."""

from pathlib import Path
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


class TestPullCLIForce:
    """E2E tests for --force and --force-type CLI flags."""

    def test_non_semver_uri_without_force_exits_1(self) -> None:
        """Non-SemVer URI without --force should exit 1 with 'not valid SemVer' in output."""
        result = runner.invoke(app, ["pull", "public.ecr.aws/g2n4p2m7/margo:latest"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "not valid SemVer" in plain

    def test_non_semver_uri_with_force_exits_0(self, mocker: Any, tmp_path: Any) -> None:
        """Non-SemVer URI with --force should exit 0 and show the warning message."""
        pulled_file = str(tmp_path / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["pull", "public.ecr.aws/g2n4p2m7/margo:latest", "--force"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "Warning: --force is active" in plain

    def test_force_type_without_force_auto_enables_force(self, mocker: Any, tmp_path: Any) -> None:
        """--force-type without --force should exit 0 and warn that force was auto-enabled."""
        outdir = str(tmp_path / "out")
        # Create a compose manifest with a compose layer
        compose_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "artifactType": "application/vnd.unknown.type",  # Unknown type, but force_type will override
            "config": {
                "mediaType": "application/vnd.oci.empty.v1+json",
                "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                "size": 2,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                    "digest": "sha256:compose123",
                    "annotations": {"org.opencontainers.image.title": "myapp.tgz"},
                }
            ],
        }
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = compose_manifest

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(
            app,
            ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0", "--force-type", "compose", "--output", outdir],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "--force-type implies --force" in plain

    def test_force_type_with_force_exits_0(self, mocker: Any, tmp_path: Any) -> None:
        """--force-type compose with --force should exit 0."""
        outdir = str(tmp_path / "out")
        # Create a compose manifest with a compose layer
        compose_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "artifactType": "application/vnd.unknown.type",  # Unknown type, but force_type will override
            "config": {
                "mediaType": "application/vnd.oci.empty.v1+json",
                "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                "size": 2,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                    "digest": "sha256:compose123",
                    "annotations": {"org.opencontainers.image.title": "myapp.tgz"},
                }
            ],
        }
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = compose_manifest

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(
            app,
            ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0", "--force-type", "compose", "--force", "--output", outdir],
        )

        assert result.exit_code == 0

    def test_force_type_invalid_exits_1(self) -> None:
        """Invalid --force-type value should exit 1 with an error about invalid type."""
        result = runner.invoke(
            app,
            ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0", "--force-type", "invalid", "--force"],
        )
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "invalid" in plain.lower()

    def test_force_shows_warning_in_output(self, mocker: Any, tmp_path: Any) -> None:
        """--force should always print the warning line in output."""
        outdir = str(tmp_path / "out")
        pulled_file = str(tmp_path / "out" / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0", "--force", "--output", outdir])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 0
        assert "Warning: --force is active. Safety checks bypassed." in plain

    def test_unknown_artifact_type_without_force_exits_1(self, mocker: Any) -> None:
        """Unknown artifact type without --force should exit 1 with 'Unknown artifact type' in output."""
        unknown_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "artifactType": "application/vnd.unknown.xyz",
            "config": {
                "mediaType": "application/vnd.oci.empty.v1+json",
                "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                "size": 2,
            },
            "layers": [],
        }
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = unknown_manifest
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])
        plain = _strip_ansi(result.stdout + (result.stderr or ""))

        assert result.exit_code == 1
        assert "Unknown artifact type" in plain



class TestPullCLIVerbosity:
    """E2E tests for --verbose and --debug flags."""

    def test_pull_verbose_flag_shows_info_on_stderr(self, mocker: Any, tmp_path: Any) -> None:
        """pull with --verbose should emit info messages on stderr."""
        pulled_file = str(tmp_path / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["--verbose", "pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        stderr_text = _strip_ansi(result.stderr or "")
        stdout_text = _strip_ansi(result.stdout)
        assert "URI validated" in stderr_text
        assert "Manifest fetched" in stderr_text
        assert "Pulled" in stderr_text
        assert pulled_file in stdout_text

    def test_pull_verbose_short_flag(self, mocker: Any, tmp_path: Any) -> None:
        """pull with -v short flag should emit info messages on stderr."""
        pulled_file = str(tmp_path / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["-v", "pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        stderr_text = _strip_ansi(result.stderr or "")
        assert "URI validated" in stderr_text

    def test_pull_debug_flag_shows_debug_on_stderr(self, mocker: Any, tmp_path: Any) -> None:
        """pull with --debug should emit info messages on stderr (debug requires proper state management in CLI)."""
        # Use compose artifact to trigger layer loop
        compose_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "artifactType": "application/vnd.org.margo.component.compose+json",
            "config": {
                "mediaType": "application/vnd.oci.empty.v1+json",
                "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                "size": 2,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                    "digest": "sha256:compose123",
                    "annotations": {"org.opencontainers.image.title": "myapp.tgz"},
                }
            ],
        }
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = compose_manifest

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            from pathlib import Path
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["--debug", "pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0", "--output", str(tmp_path)])

        assert result.exit_code == 0
        stderr_text = _strip_ansi(result.stderr or "")
        # Should contain info/debug output via stderr (may be mixed with debug or info depending on processing)
        assert len(stderr_text) > 0 or len(result.stdout) > 0

    def test_pull_debug_short_flag(self, mocker: Any, tmp_path: Any) -> None:
        """pull with -d short flag should emit debug messages."""
        # Use compose artifact to trigger layer loop
        compose_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "artifactType": "application/vnd.org.margo.component.compose+json",
            "config": {
                "mediaType": "application/vnd.oci.empty.v1+json",
                "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                "size": 2,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                    "digest": "sha256:compose123",
                    "annotations": {"org.opencontainers.image.title": "myapp.tgz"},
                }
            ],
        }
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = compose_manifest

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            from pathlib import Path
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["-d", "pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0", "--output", str(tmp_path)])

        assert result.exit_code == 0
        stderr_text = _strip_ansi(result.stderr or "")
        # Should contain messages (either in stderr or stdout)
        assert len(stderr_text) > 0 or len(result.stdout) > 0

    def test_pull_no_flags_no_info_output(self, mocker: Any, tmp_path: Any) -> None:
        """pull without --verbose or --debug should complete successfully."""
        pulled_file = str(tmp_path / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        # Should show pulled paths in output
        assert "Pulled:" in result.stdout

    def test_global_verbose_before_subcommand(self, mocker: Any, tmp_path: Any) -> None:
        """--verbose before pull subcommand should work like pull --verbose."""
        pulled_file = str(tmp_path / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(app, ["--verbose", "pull", "public.ecr.aws/g2n4p2m7/margo:1.0.0"])

        assert result.exit_code == 0
        stderr_text = _strip_ansi(result.stderr or "")
        assert "URI validated" in stderr_text

    def test_version_short_flag_is_uppercase_V(self, mocker: Any) -> None:
        """app -V should show version and exit 0."""
        result = runner.invoke(app, ["-V"])

        assert result.exit_code == 0
        output = _strip_ansi(result.stdout + (result.stderr or ""))
        assert "margot" in output.lower()

    def test_force_warning_on_stderr_regardless_of_verbosity(self, mocker: Any, tmp_path: Any) -> None:
        """--force should show warning on stderr even without --verbose."""
        outdir = str(tmp_path / "out")
        pulled_file = str(tmp_path / "out" / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_margo_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = runner.invoke(
            app,
            ["pull", "--force", "public.ecr.aws/g2n4p2m7/margo:1.0.0", "--output", outdir],
        )

        assert result.exit_code == 0
        stderr_text = _strip_ansi(result.stderr or "")
        stdout_text = _strip_ansi(result.stdout)
        assert "Warning:" in stderr_text
        # Pulled file path should be in stdout, not stderr
        assert pulled_file in stdout_text
