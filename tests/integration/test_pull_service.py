"""Integration tests for services/pull.py."""

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
        """For a compose artifact with a layer title annotation, should rename the pulled file."""
        original_file = tmp_path / "sha256abc.tar.gz"
        original_file.write_bytes(b"fake archive content")

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
        mock_client.pull.return_value = [str(original_file)]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        assert result == [str(tmp_path / "myapp-1.0.0.tgz")]
        assert (tmp_path / "myapp-1.0.0.tgz").exists()
        assert not original_file.exists()

    def test_compose_artifact_with_manifest_annotations_constructs_filename(self, mocker: Any, tmp_path: Any) -> None:
        """For a compose artifact with manifest-level annotations, should construct filename."""
        original_file = tmp_path / "sha256abc.tar.gz"
        original_file.write_bytes(b"fake archive content")

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
        mock_client.pull.return_value = [str(original_file)]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        assert result == [str(tmp_path / "myapp-2.3.1.tgz")]
        assert (tmp_path / "myapp-2.3.1.tgz").exists()

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
        """force_type provided without force=True should now be accepted by the service."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_client.pull.return_value = [str(tmp_path / "margo.yaml")]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        # Must not raise — the service no longer enforces force=True when force_type is set
        pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force_type=PackageType.COMPOSE,
        )

        mock_client.pull.assert_called_once()

    def test_force_type_with_force_overrides_detected_type(self, mocker: Any, tmp_path: Any) -> None:
        """force_type with force=True should override the detected artifact type."""
        original_file = tmp_path / "sha256abc.tar.gz"
        original_file.write_bytes(b"fake archive content")

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
        mock_client.pull.return_value = [str(original_file)]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force=True,
            force_type=PackageType.COMPOSE,
        )

        # Should have applied compose naming: renamed to layer title
        assert result == [str(tmp_path / "myapp-1.0.0.tgz")]
        assert (tmp_path / "myapp-1.0.0.tgz").exists()

    def test_malicious_layer_title_force_false_does_not_rename_to_traversal_path(self, mocker: Any, tmp_path: Any) -> None:
        """Malicious layer title with force=False should NOT rename to a traversal path."""
        original_file = tmp_path / "sha256abc.tar.gz"
        original_file.write_bytes(b"fake archive content")

        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abc",
                "annotations": {"org.opencontainers.image.title": "../../evil.tgz"},
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
        )
        mock_client.pull.return_value = [str(original_file)]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force=False,
        )

        # Unsafe title is rejected; no manifest annotations to fall back to — file kept as-is
        assert result == [str(original_file)]
        assert original_file.exists()
        # Traversal path should NOT have been created
        evil_path = tmp_path.parent.parent / "evil.tgz"
        assert not evil_path.exists()

    def test_malicious_layer_title_force_true_uses_raw_name(self, mocker: Any, tmp_path: Any) -> None:
        """Malicious layer title with force=True should use the raw name (rename attempted)."""
        # Use a sub-directory so that "../../evil.tgz" resolves within tmp_path's parent
        subdir = tmp_path / "sub" / "dir"
        subdir.mkdir(parents=True)
        original_file = subdir / "sha256abc.tar.gz"
        original_file.write_bytes(b"fake archive content")

        layers = [
            {
                "mediaType": "application/vnd.org.margo.component.compose.tar+gzip",
                "digest": "sha256:abc",
                "annotations": {"org.opencontainers.image.title": "../../evil.tgz"},
            }
        ]
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json",
            layers=layers,
        )
        mock_client.pull.return_value = [str(original_file)]
        mocker.patch("margot.services.pull.oci.OrasClient", return_value=mock_client)

        result = pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(subdir),
            force=True,
        )

        # Raw name is used — returned path contains the traversal string
        assert len(result) == 1
        assert "../../evil.tgz" in result[0] or result[0].endswith("evil.tgz")
        # Original file was moved
        assert not original_file.exists()
