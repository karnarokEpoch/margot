"""Integration tests for services/pull.py."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pytest import raises

from margot.domain.models import PackageType
from margot.services import pull as pull_service


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
        mock_class = mocker.patch("margot.services.pull.oci.OrasClient")

        with raises(ValueError, match="URI must not be empty"):
            pull_service.pull_artifact("", outdir=str(tmp_path))

        mock_class.assert_not_called()

    def test_propagates_exception_from_pull(self, mocker: Any, tmp_path: Any) -> None:
        """Should propagate exceptions raised by client.pull."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.side_effect = Exception("Network error")
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        with raises(Exception, match="Network error"):
            pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

    def test_returns_empty_list_when_pull_returns_nothing(self, mocker: Any, tmp_path: Any) -> None:
        """Should return empty list without error when oras returns no paths."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = []
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        assert result == []


class TestPullArtifactForce:
    """Integration tests for force/force-type parameters in pull_artifact()."""

    def test_non_semver_tag_without_force_raises(self, mocker: Any, tmp_path: Any) -> None:
        """Non-SemVer tag without --force should raise ValueError."""
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
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(subdir),
            force=True,
        )

        # Should include the raw title in the path
        assert len(result) == 1
        assert "../../evil.tgz" in result[0]
