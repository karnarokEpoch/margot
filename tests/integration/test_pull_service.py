"""Integration tests for services/pull.py."""

from typing import Any
from unittest.mock import MagicMock

from pytest import raises

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

    # TODO(karnarokEpoch): Should also have a test for malicious title renames and we should succeed it.
    # Traversal path, weird charaters in path...
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
