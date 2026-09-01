"""Integration tests for services/pull.py."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pytest import raises

from margot import console
from margot.domain.models import PackageType
from margot.infra.credentials import CredentialsExpiredError
from margot.services import pull as pull_service
from margot.services.pull import _available_layer_types


def _make_manifest(
    artifact_type: str = "application/vnd.margo.app.v1+json",
    layers: list[dict[str, Any]] | None = None,
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal OCI manifest dict for testing."""
    manifest: dict[str, Any] = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": artifact_type,
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "size": 2,
        },
        "layers": layers if layers is not None else [],
    }
    if annotations is not None:
        manifest["annotations"] = annotations
    return manifest


class TestPullArtifactService:
    """Integration tests for pull_artifact()."""

    def test_calls_get_manifest_then_pull(self, mocker: Any, tmp_path: Any) -> None:
        """Should call client.get_manifest(uri) then client.pull(target=uri, outdir=outdir)."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [str(tmp_path / "margo.yaml")]
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        mock_client.get_manifest.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0")
        mock_client.pull.assert_called_once_with(uri="public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

    def test_margo_artifact_returns_paths_without_renaming(self, mocker: Any, tmp_path: Any) -> None:
        """For a margo artifact, should return oras paths as-is without renaming."""
        expected_paths = [str(tmp_path / "margo.yaml"), str(tmp_path / "README.md")]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.margo.app.v1+json",
        )
        mock_client.pull.return_value = expected_paths
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        assert result == expected_paths

    def test_compose_artifact_with_layer_title_renames_file(self, mocker: Any, tmp_path: Any) -> None:
        """For a compose artifact with a layer title annotation, should download blob with that title."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abc",
                "annotations": {"org.opencontainers.image.title": "myapp-1.0.0.tgz"},
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake archive content")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        assert result == [str(tmp_path / "myapp-1.0.0.tgz")]
        assert (tmp_path / "myapp-1.0.0.tgz").exists()
        mock_client.download_blob.assert_called_once_with(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            "sha256:abc",
            str(tmp_path / "myapp-1.0.0.tgz"),
        )

    def test_compose_artifact_with_manifest_annotations_constructs_filename(self, mocker: Any, tmp_path: Any) -> None:
        """For a compose artifact with manifest-level annotations, should download to constructed filename."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abc",
            }
        ]
        manifest_annotations = {
            "org.opencontainers.image.title": "myapp",
            "org.opencontainers.image.version": "2.3.1",
        }
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
            annotations=manifest_annotations,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake archive content")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        assert result == [str(tmp_path / "myapp-2.3.1.tgz")]
        assert (tmp_path / "myapp-2.3.1.tgz").exists()
        mock_client.download_blob.assert_called_once_with(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            "sha256:abc",
            str(tmp_path / "myapp-2.3.1.tgz"),
        )

    def test_raises_value_error_on_empty_uri(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError before making any client call when URI is empty."""
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mock_class = mocker.patch("margot.services.pull.oci.OrasClient")

        with raises(ValueError, match="URI must not be empty"):
            pull_service.pull_artifact("", outdir=str(tmp_path))

        mock_class.assert_not_called()

    def test_propagates_exception_from_pull(self, mocker: Any, tmp_path: Any) -> None:
        """Should propagate exceptions raised by client.pull."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.side_effect = Exception("Network error")
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        with raises(Exception, match="Network error"):
            pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

    def test_returns_empty_list_when_pull_returns_nothing(self, mocker: Any, tmp_path: Any) -> None:
        """Should return empty list without error when oras returns no paths."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = []
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        assert result == []


class TestPullArtifactForce:
    """Integration tests for force/force-type parameters in pull_artifact()."""

    def test_non_semver_tag_without_force_raises(self, mocker: Any, tmp_path: Any) -> None:
        """Non-SemVer tag without --force should raise ValueError."""
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient")

        with raises(ValueError, match="not valid SemVer"):
            pull_service.pull_artifact(
                "public.ecr.aws/g2n4p2m7/margo:latest",
                outdir=str(tmp_path),
            )

    def test_non_semver_tag_with_force_proceeds(self, mocker: Any, tmp_path: Any) -> None:
        """Non-SemVer tag with force=True should proceed and call client.pull."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [str(tmp_path / "margo.yaml")]
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:latest",
            outdir=str(tmp_path),
            force=True,
        )

        mock_client.pull.assert_called_once()

    def test_force_type_without_force_is_accepted(self, mocker: Any, tmp_path: Any) -> None:
        """force_type without force=True is accepted — no SemVer or unknown-type guard fires."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abc",
                "annotations": {"org.opencontainers.image.title": "myapp-1.0.0.tgz"},
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        # Must not raise — force_type without force is valid for a SemVer tag + known type
        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force_type=PackageType.COMPOSE,
        )

        assert result == [str(tmp_path / "myapp-1.0.0.tgz")]

    def test_force_type_with_force_overrides_detected_type(self, mocker: Any, tmp_path: Any) -> None:
        """force_type with force=True should override the detected artifact type."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abc",
                "annotations": {"org.opencontainers.image.title": "myapp-1.0.0.tgz"},
            }
        ]
        # Manifest reports UNKNOWN artifact type, but force_type overrides to COMPOSE
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.unknown.type",
            layers=layers,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake archive content")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force=True,
            force_type=PackageType.COMPOSE,
        )

        # Should have applied compose naming: downloaded to layer title
        assert result == [str(tmp_path / "myapp-1.0.0.tgz")]
        assert (tmp_path / "myapp-1.0.0.tgz").exists()
        mock_client.download_blob.assert_called_once_with(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            "sha256:abc",
            str(tmp_path / "myapp-1.0.0.tgz"),
        )

    def test_malicious_layer_title_force_false_does_not_rename_to_traversal_path(self, mocker: Any, tmp_path: Any) -> None:
        """Malicious layer title with force=False should use digest-based fallback name, not traversal path."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abcdef123456",
                "annotations": {"org.opencontainers.image.title": "../../evil.tgz"},
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake archive content")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force=False,
        )

        # Unsafe title is rejected; no manifest annotations; use digest-based fallback
        # digest_hex = "sha256:abcdef123456"[-12:] = "bcdef123456" (first 12 chars of hex after sha256:)
        # Actually: sha256:abcdef123456.split(":", 1)[-1][:12] = abcdef123456[:12] = abcdef123456
        expected_name = "abcdef123456"
        assert result == [str(tmp_path / expected_name)]
        assert (tmp_path / expected_name).exists()
        # Ensure traversal path was not created
        assert not (tmp_path.parent.parent / "evil.tgz").exists()

    def test_unknown_artifact_type_without_force_raises(self, mocker: Any, tmp_path: Any) -> None:
        """Unknown artifact type without force should raise ValueError."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.docker.container.image.v1+json",
        )
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        with raises(ValueError, match=r"Unknown artifact type.*--force"):
            pull_service.pull_artifact(
                "public.ecr.aws/g2n4p2m7/margo:1.0.0",
                outdir=str(tmp_path),
                force=False,
            )

    def test_unknown_artifact_type_with_force_calls_pull(self, mocker: Any, tmp_path: Any) -> None:
        """Unknown artifact type with force=True should call client.pull() and return result."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.docker.container.image.v1+json",
        )
        mock_client.pull.return_value = [str(tmp_path / "layer.tar.gz")]
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force=True,
        )

        assert result == [str(tmp_path / "layer.tar.gz")]
        mock_client.pull.assert_called_once()

    def test_none_artifact_type_without_force_raises(self, mocker: Any, tmp_path: Any) -> None:
        """None artifact type without force should raise ValueError containing '(none)'."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(artifact_type=None)
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        with raises(ValueError, match=r"Unknown artifact type.*\(none\).*--force"):
            pull_service.pull_artifact(
                "public.ecr.aws/g2n4p2m7/margo:1.0.0",
                outdir=str(tmp_path),
                force=False,
            )


class TestPullLayerLoop:
    """Tests for the new layer loop implementation in pull_artifact."""

    def test_pull_force_type_mismatch_raises(self, mocker: Any, tmp_path: Any) -> None:
        """Manifest has quadlet layer, force_type=COMPOSE → raises ValueError with layer info."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.quadlet.tar+gzip",
                "digest": "sha256:quad123",
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.quadlet+json",
            layers=layers,
        )
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        with raises(ValueError, match="No layer with mediaType"):
            pull_service.pull_artifact(
                "public.ecr.aws/g2n4p2m7/margo:1.0.0",
                outdir=str(tmp_path),
                force=True,
                force_type=PackageType.COMPOSE,
            )

    def test_pull_downloads_only_matching_layer(self, mocker: Any, tmp_path: Any) -> None:
        """Manifest has quadlet + description layers. Pull quadlet only."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.quadlet.tar+gzip",
                "digest": "sha256:quadlet",
                "annotations": {"org.opencontainers.image.title": "app.quadlet"},
            },
            {
                "mediaType": "application/vnd.margo.app.description.v1+yaml",
                "digest": "sha256:desc",
                "annotations": {"org.opencontainers.image.title": "margo.yaml"},
            },
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.quadlet+json",
            layers=layers,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake content")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force=True,
            force_type=PackageType.QUADLET,
        )

        # Only quadlet layer should be downloaded
        assert len(result) == 1
        assert result[0].endswith("app.quadlet")
        mock_client.download_blob.assert_called_once()
        call_args = mock_client.download_blob.call_args
        assert call_args[0][1] == "sha256:quadlet"  # digest is second arg

    def test_pull_malicious_title_rejected(self, mocker: Any, tmp_path: Any) -> None:
        """Compose layer with malicious title, force=False → uses digest fallback."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abc1234567890",
                "annotations": {"org.opencontainers.image.title": "../../evil.tgz"},
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force=False,
        )

        # Should use digest-based name (first 12 chars of hex after sha256:)
        assert len(result) == 1
        assert "evil" not in result[0]
        assert "/../../" not in result[0]

    def test_pull_malicious_title_allowed_with_force(self, mocker: Any, tmp_path: Any) -> None:
        """Compose layer with malicious title, force=True → downloads with raw title."""
        subdir = tmp_path / "sub" / "dir"
        subdir.mkdir(parents=True)

        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:compose",
                "annotations": {"org.opencontainers.image.title": "../../evil.tgz"},
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(subdir),
            force=True,
        )

        # Should include the raw title in the path
        assert len(result) == 1
        assert "../../evil.tgz" in result[0]


class TestPullArtifactVerbose:
    """Tests for pull_artifact() with verbose output."""

    def test_pull_emits_info_when_verbose(
        self, mocker: Any, tmp_path: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """pull_artifact() should emit info messages on stderr when verbose=True."""

        console.set_verbose(True)
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [str(tmp_path / "margo.yaml")]
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)
        out, err = capture_console
        pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))
        err_text = err.getvalue()
        assert "URI validated" in err_text
        assert "Manifest fetched" in err_text
        assert "Pulled" in err_text
        assert out.getvalue() == ""

    def test_pull_no_info_without_verbose(
        self, mocker: Any, tmp_path: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """pull_artifact() should emit no info messages when verbose=False."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [str(tmp_path / "margo.yaml")]
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)
        out, err = capture_console
        pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))
        assert err.getvalue() == ""
        assert out.getvalue() == ""


class TestAvailableLayerTypes:
    """Unit tests for _available_layer_types helper."""

    def test_empty_layers_returns_no_layers_present(self) -> None:
        """Should return 'No layers present.' for an empty list."""
        result = _available_layer_types([])

        assert result == "No layers present."

    def test_known_media_type_shows_friendly_name(self) -> None:
        """Should include friendly name and full media type for known types."""
        layers = [{"mediaType": "application/vnd.org.margo.component.compose.tar+gzip"}]

        result = _available_layer_types(layers)

        assert "compose" in result
        assert "application/vnd.org.margo.component.compose.tar+gzip" in result

    def test_unknown_media_type_shows_raw_string(self) -> None:
        """Should show raw mediaType string without friendly name wrapper for unknown types."""
        layers = [{"mediaType": "application/vnd.unknown.type+json"}]

        result = _available_layer_types(layers)

        assert "application/vnd.unknown.type+json" in result
        assert result == "Available layer types: application/vnd.unknown.type+json"


class TestPullArtifactAuth:
    """Tests for authenticated pull_artifact(): hostname extraction, credential checks."""

    def test_pull_checks_credentials_for_hostname(self, mocker: Any, tmp_path: Any) -> None:
        """Should call check_credentials with the hostname extracted from the URI."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [str(tmp_path / "margo.yaml")]
        mock_check_credentials = mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        mock_check_credentials.assert_called_once_with("public.ecr.aws")

    def test_pull_passes_hostname_to_oras_client(self, mocker: Any, tmp_path: Any) -> None:
        """Should construct OrasClient with hostname=<extracted hostname>."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [str(tmp_path / "margo.yaml")]
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mock_oras_client_cls = mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        mock_oras_client_cls.assert_called_once_with(hostname="public.ecr.aws")

    def test_pull_expired_credentials_propagates(self, mocker: Any, tmp_path: Any) -> None:
        """Should propagate CredentialsExpiredError raised by check_credentials before constructing a client."""
        mock_oras_client_cls = mocker.patch("margot.services.pull.oci.OrasClient")
        mocker.patch(
            "margot.services.pull.credentials.check_credentials",
            side_effect=CredentialsExpiredError("Credentials for public.ecr.aws have expired."),
        )

        with raises(CredentialsExpiredError, match="expired"):
            pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        mock_oras_client_cls.assert_not_called()

    def test_pull_near_expiry_warns_but_proceeds(
        self, mocker: Any, tmp_path: Any, capture_console: tuple[Any, Any], reset_console: None
    ) -> None:
        """Near-expiry credentials should emit a console.warning but still pull and return paths."""

        def _warn_and_proceed(_registry: str) -> None:
            console.warning("Credentials for public.ecr.aws expire in less than 1 hour.")

        pulled_file = str(tmp_path / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [pulled_file]
        mocker.patch("margot.services.pull.credentials.check_credentials", side_effect=_warn_and_proceed)
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)
        _out, err = capture_console

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        assert "warning" in err.getvalue().lower()
        assert "expire in less than" in err.getvalue()
        assert result == [pulled_file]

    def test_pull_no_tracked_credentials_proceeds_anonymously(self, mocker: Any, tmp_path: Any) -> None:
        """When no credentials are tracked for the registry, check_credentials is a no-op and pull proceeds."""
        pulled_file = str(tmp_path / "margo.yaml")
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [pulled_file]
        # check_credentials with no tracked expiry returns None silently (real behavior, not mocked away)
        mocker.patch("margot.services.pull.credentials.load_expiry", return_value=None)
        mock_oras_client_cls = mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        mock_oras_client_cls.assert_called_once_with(hostname="public.ecr.aws")
        assert result == [pulled_file]


class TestPullArtifactRecursive:
    """Integration tests for recursive component pulling in margo artifacts."""

    def test_recursive_pull_margo_with_components(self, mocker: Any, tmp_path: Any) -> None:
        """recursive=True on margo artifact should pull components into subdirectories."""
        # Root margo artifact manifest
        root_manifest = _make_manifest(artifact_type="application/vnd.margo.app.v1+json")

        # Component refs from the app.yaml
        component1_layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:comp1",
                "annotations": {"org.opencontainers.image.title": "postgres-14.0.0.tgz"},
            }
        ]
        component1_manifest = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=component1_layers,
        )

        component2_layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:comp2",
                "annotations": {"org.opencontainers.image.title": "redis-7.0.0.tgz"},
            }
        ]
        component2_manifest = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=component2_layers,
        )

        # Create a temporary app.yaml for the root
        app_yaml_content = """\
apiVersion: v1
kind: ApplicationDescription
id: test-app
metadata:
  name: Test App
  version: 1.0.0
deploymentProfiles:
  - type: helm
    id: default
    components:
      - name: database
        properties:
          repository: oci://quay.io/charts/postgres
          revision: 14.0.0
      - name: cache
        properties:
          repository: oci://quay.io/charts/redis
          revision: 7.0.0
"""

        # Mock the client
        mock_client = MagicMock()

        # Return different manifests depending on the URI
        def manifest_side_effect(uri: str) -> dict[str, Any]:
            if "postgres" in uri:
                return component1_manifest
            if "redis" in uri:
                return component2_manifest
            return root_manifest

        mock_client.get_manifest.side_effect = manifest_side_effect

        # Mock download_blob to write fake data
        def download_blob_side_effect(_uri: str, _digest: str, outfile: str) -> None:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake archive")

        mock_client.download_blob.side_effect = download_blob_side_effect

        # Mock pull to return app.yaml for root
        def pull_side_effect(uri: str, outdir: str) -> list[str]:
            Path(outdir).mkdir(parents=True, exist_ok=True)
            if uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0":
                # Root pull
                path = Path(outdir) / "app.yaml"
                path.write_text(app_yaml_content)
                return [str(path)]
            return []

        mock_client.pull.side_effect = pull_side_effect
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            recursive=True,
        )

        # Should have root + 2 components = 3 paths
        assert len(result) == 3
        assert any("app.yaml" in path for path in result)
        assert any("database" in path and "postgres" in path for path in result)
        assert any("cache" in path and "redis" in path for path in result)

    def test_recursive_pull_margo_with_missing_component_properties(self, mocker: Any, tmp_path: Any) -> None:
        """recursive=True should skip components with missing properties and emit warnings."""
        root_manifest = _make_manifest(artifact_type="application/vnd.margo.app.v1+json")

        # App with one valid and one incomplete component
        app_yaml_content = """\
apiVersion: v1
kind: ApplicationDescription
id: test-app
metadata:
  name: Test App
  version: 1.0.0
deploymentProfiles:
  - type: helm
    id: default
    components:
      - name: valid-component
        properties:
          repository: oci://quay.io/charts/valid
          revision: 1.0.0
      - name: incomplete-component
        properties:
          revision: 2.0.0
"""
        app_yaml_path = tmp_path / "app.yaml"
        app_yaml_path.write_text(app_yaml_content)

        mock_client = MagicMock()
        mock_client.get_manifest.return_value = root_manifest

        def pull_side_effect(uri: str, outdir: str) -> list[str]:
            Path(outdir).mkdir(parents=True, exist_ok=True)
            if uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0":
                path = Path(outdir) / "app.yaml"
                path.write_text(app_yaml_content)
                return [str(path)]
            if "valid" in uri:
                path = Path(outdir) / "valid-1.0.0.tgz"
                path.write_bytes(b"valid tar")
                return [str(path)]
            return []

        mock_client.pull.side_effect = pull_side_effect
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        # Capture warnings
        warning_mock = mocker.patch("margot.services.pull.console.warning")

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            recursive=True,
        )

        # Should have root + 1 valid component
        assert len(result) == 2
        # Should have warned about incomplete-component
        warning_mock.assert_any_call("Skipping component 'incomplete-component': missing repository or revision properties.")

    def test_recursive_pull_margo_app_yaml_missing(self, mocker: Any, tmp_path: Any) -> None:
        """recursive=True when app.yaml is missing should emit warning and return root paths only."""
        root_manifest = _make_manifest(artifact_type="application/vnd.margo.app.v1+json")

        # Pulled paths without app.yaml
        root_paths = [str(tmp_path / "README.md"), str(tmp_path / "resources.tar.gz")]
        for path in root_paths:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"fake")

        mock_client = MagicMock()
        mock_client.get_manifest.return_value = root_manifest
        mock_client.pull.return_value = root_paths

        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        warning_mock = mocker.patch("margot.services.pull.console.warning")

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            recursive=True,
        )

        # Should return root paths only
        assert result == root_paths
        # Should warn about missing app.yaml
        warning_mock.assert_called_once()
        assert "app.yaml" in warning_mock.call_args[0][0].lower()

    def test_recursive_pull_margo_app_yaml_unparseable(self, mocker: Any, tmp_path: Any) -> None:
        """recursive=True when app.yaml is unparseable should emit warning and return root paths only."""
        root_manifest = _make_manifest(artifact_type="application/vnd.margo.app.v1+json")

        # Create invalid YAML
        app_yaml_path = tmp_path / "app.yaml"
        app_yaml_path.write_text("{ invalid: yaml: content:")

        root_paths = [str(app_yaml_path)]

        mock_client = MagicMock()
        mock_client.get_manifest.return_value = root_manifest
        mock_client.pull.return_value = root_paths

        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        warning_mock = mocker.patch("margot.services.pull.console.warning")

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            recursive=True,
        )

        # Should return root paths only
        assert result == root_paths
        # Should warn about parse error
        warning_mock.assert_called_once()
        assert "Failed to load app.yaml" in warning_mock.call_args[0][0]

    def test_recursive_pull_non_margo_is_noop(self, mocker: Any, tmp_path: Any) -> None:
        """recursive=True on non-margo (e.g., compose) should be a no-op, identical to recursive=False."""
        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abc",
                "annotations": {"org.opencontainers.image.title": "myapp.tgz"},
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
        )

        def _fake_download(_uri: str, _digest: str, outfile: str) -> str:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake")
            return outfile

        mock_client.download_blob.side_effect = _fake_download
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result_recursive = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path / "recursive"),
            recursive=True,
        )

        # Create a fresh tmp_path for non-recursive to compare
        result_non_recursive = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path / "non_recursive"),
            recursive=False,
        )

        # Both should have 1 file (no difference in behavior)
        assert len(result_recursive) == 1
        assert len(result_non_recursive) == 1
        # Both files should exist at the same relative names
        assert (tmp_path / "recursive" / "myapp.tgz").exists()
        assert (tmp_path / "non_recursive" / "myapp.tgz").exists()

    def test_recursive_pull_component_failure_does_not_crash_root(self, mocker: Any, tmp_path: Any) -> None:
        """If one component fails to pull, warning is emitted but root and other components are returned."""
        root_manifest = _make_manifest(artifact_type="application/vnd.margo.app.v1+json")

        good_layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:good",
                "annotations": {"org.opencontainers.image.title": "good.tgz"},
            }
        ]
        component_manifest = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=good_layers,
        )

        app_yaml_content = """\
apiVersion: v1
kind: ApplicationDescription
id: test-app
metadata:
  name: Test App
  version: 1.0.0
deploymentProfiles:
  - type: helm
    id: default
    components:
      - name: good-comp
        properties:
          repository: oci://quay.io/charts/good
          revision: 1.0.0
      - name: bad-comp
        properties:
          repository: oci://quay.io/charts/bad
          revision: 2.0.0
"""

        mock_client = MagicMock()

        def manifest_side_effect(uri: str) -> dict[str, Any]:
            if "bad" in uri:
                raise RuntimeError("Registry error for bad component")
            if "good" in uri:
                return component_manifest
            return root_manifest

        mock_client.get_manifest.side_effect = manifest_side_effect

        def download_blob_side_effect(_uri: str, _digest: str, outfile: str) -> None:
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            Path(outfile).write_bytes(b"fake tar")

        mock_client.download_blob.side_effect = download_blob_side_effect

        def pull_side_effect(uri: str, outdir: str) -> list[str]:
            if "bad" in uri:
                raise RuntimeError("Registry error for bad component")
            Path(outdir).mkdir(parents=True, exist_ok=True)
            if uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0":
                path = Path(outdir) / "app.yaml"
                path.write_text(app_yaml_content)
                return [str(path)]
            return []

        mock_client.pull.side_effect = pull_side_effect
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        warning_mock = mocker.patch("margot.services.pull.console.warning")

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            recursive=True,
        )

        # Should have root + good component
        assert len(result) == 2
        assert any("app.yaml" in path for path in result)
        assert any("good" in path for path in result)
        # Should have warned about bad-comp
        assert any("bad-comp" in str(call) for call in warning_mock.call_args_list)
