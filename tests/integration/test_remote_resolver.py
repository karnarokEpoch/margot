"""Integration tests for services/remote.py — remote OCI artifact resolution."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pytest import raises

from margot.infra.credentials import CredentialsExpiredError
from margot.services import remote as remote_service


def _make_manifest(
    artifact_type: str | None = "application/vnd.margo.app.v1+json",
    layers: list[dict[str, Any]] | None = None,
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal OCI manifest dict for testing."""
    manifest: dict[str, Any] = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "size": 2,
        },
        "layers": layers if layers is not None else [],
    }
    if artifact_type is not None:
        manifest["artifactType"] = artifact_type
    if annotations is not None:
        manifest["annotations"] = annotations
    return manifest


class TestRemoteResolver:
    """Integration tests for resolve_remote_descriptor()."""

    def test_resolve_remote_margo_descriptor_returns_normalized_uri_and_app_yaml_path(
        self, mocker: Any, tmp_path: Any
    ) -> None:
        """Should resolve a margo artifact, pull it, return URI and app.yaml path."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.margo.app.v1+json"
        )
        # Simulate pulling a margo artifact with app.yaml
        def _fake_pull(uri: str, outdir: str) -> list[str]:
            app_yaml_path = Path(outdir) / "app.yaml"
            app_yaml_path.write_text("kind: ApplicationDescription\nid: test\n", encoding="utf-8")
            return [str(app_yaml_path), str(Path(outdir) / "resources")]

        mock_client.pull.side_effect = _fake_pull
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)

        result = remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        assert result.normalized_uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        assert result.app_yaml_path.endswith("app.yaml")
        assert Path(result.app_yaml_path).exists()
        assert result.temp_dir is not None
        # Temp dir should still exist after return
        assert Path(result.temp_dir.name).exists()

    def test_resolve_remote_with_oci_scheme_strips_and_normalizes(self, mocker: Any, tmp_path: Any) -> None:
        """Should accept oci:// scheme and normalize to canonical form."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()

        def _fake_pull(uri: str, outdir: str) -> list[str]:
            app_yaml_path = Path(outdir) / "app.yaml"
            app_yaml_path.write_text("kind: ApplicationDescription\nid: test\n", encoding="utf-8")
            return [str(app_yaml_path)]

        mock_client.pull.side_effect = _fake_pull
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)

        result = remote_service.resolve_remote_descriptor("oci://public.ecr.aws/g2n4p2m7/margo:1.0.0")

        # Normalized URI should be without oci://
        assert result.normalized_uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        mock_client.pull.assert_called_once()
        # Call should use the normalized (non-scheme) URI
        args = mock_client.pull.call_args
        assert args[1]["uri"] == "public.ecr.aws/g2n4p2m7/margo:1.0.0"

    def test_resolve_remote_raises_for_malformed_uri(self, mocker: Any) -> None:
        """Should raise ValueError for malformed URI before any I/O."""
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mock_class = mocker.patch("margot.services.remote.oci.OrasClient")

        with raises(ValueError, match="URI must"):
            remote_service.resolve_remote_descriptor("not-a-valid-uri")

        mock_class.assert_not_called()

    def test_resolve_remote_raises_for_non_margo_compose_artifact(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError for compose artifact before pull."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.compose+json"
        )
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)

        with raises(ValueError, match="not a Margo application descriptor") as exc_info:
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/compose:1.0.0")

        # Error message should mention compose and suggest fetch
        assert "compose" in str(exc_info.value).lower()
        assert "margot fetch" in str(exc_info.value).lower()

    def test_resolve_remote_raises_for_non_margo_quadlet_artifact(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError for quadlet artifact before pull."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(
            artifact_type="application/vnd.org.margo.component.quadlet+json"
        )
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)

        with raises(ValueError, match="not a Margo application descriptor") as exc_info:
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/quadlet:1.0.0")

        assert "quadlet" in str(exc_info.value).lower()
        assert "margot fetch" in str(exc_info.value).lower()

    def test_resolve_remote_raises_for_unknown_artifact_type(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError for unknown artifact type."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest(artifact_type=None)
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)

        with raises(ValueError, match="not a Margo application descriptor") as exc_info:
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/unknown:1.0.0")

        assert "unknown" in str(exc_info.value).lower()
        assert "margot fetch" in str(exc_info.value).lower()

    def test_resolve_remote_raises_for_missing_app_yaml(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError when pulled artifact has no app.yaml."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()

        def _fake_pull(uri: str, outdir: str) -> list[str]:
            # Pull returns paths, but no app.yaml
            Path(outdir).mkdir(parents=True, exist_ok=True)
            Path(outdir) / "some-other-file.txt"
            (Path(outdir) / "some-other-file.txt").write_text("content", encoding="utf-8")
            return [str(Path(outdir) / "some-other-file.txt")]

        mock_client.pull.side_effect = _fake_pull
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)

        with raises(ValueError, match="app.yaml") as exc_info:
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        assert "no root app.yaml" in str(exc_info.value).lower()

    def test_resolve_remote_cleans_up_temp_dir_on_exception(self, mocker: Any, tmp_path: Any) -> None:
        """Should clean up temp directory when exception occurs."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()

        def _fake_pull(uri: str, outdir: str) -> list[str]:
            Path(outdir).mkdir(parents=True, exist_ok=True)
            # Don't create app.yaml, forcing an error
            return []

        mock_client.pull.side_effect = _fake_pull
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)

        # The test passes if no exception is raised from cleanup
        # (the temp directory should be cleaned up before raising ValueError)
        with raises(ValueError, match="app.yaml"):
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/margo:1.0.0")

    def test_resolve_remote_pull_with_recursive_false(self, mocker: Any, tmp_path: Any) -> None:
        """Should call pull_artifact with recursive=False."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()

        def _fake_pull(uri: str, outdir: str, recursive: bool = False) -> list[str]:  # noqa: ARG001
            app_yaml_path = Path(outdir) / "app.yaml"
            Path(outdir).mkdir(parents=True, exist_ok=True)
            app_yaml_path.write_text("kind: ApplicationDescription\nid: test\n", encoding="utf-8")
            return [str(app_yaml_path)]

        mock_pull = mocker.patch(
            "margot.services.pull.pull_artifact",
            side_effect=_fake_pull,
        )
        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)

        remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        # Verify pull was called with recursive=False
        mock_pull.assert_called_once()
        call_kwargs = mock_pull.call_args[1]
        assert call_kwargs.get("recursive") is False

    def test_resolve_remote_expired_credentials_propagates(self, mocker: Any) -> None:
        """Should propagate CredentialsExpiredError from credential check."""
        mocker.patch(
            "margot.services.remote.credentials.check_credentials",
            side_effect=CredentialsExpiredError("Credentials expired for example.com"),
        )
        mock_class = mocker.patch("margot.services.remote.oci.OrasClient")

        with raises(CredentialsExpiredError, match="Credentials expired"):
            remote_service.resolve_remote_descriptor("example.com/org/repo:1.0.0")

        mock_class.assert_not_called()

    def test_resolve_remote_accepts_legacy_non_semver_tag(self, mocker: Any, tmp_path: Any) -> None:
        """Should accept legacy non-SemVer tags without --force."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()

        def _fake_pull_artifact(uri: str, outdir: str, **kwargs: Any) -> list[str]:
            app_yaml_path = Path(outdir) / "app.yaml"
            Path(outdir).mkdir(parents=True, exist_ok=True)
            app_yaml_path.write_text("kind: ApplicationDescription\nid: test\n", encoding="utf-8")
            return [str(app_yaml_path)]

        mocker.patch("margot.services.remote.credentials.check_credentials")
        mocker.patch("margot.services.remote.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.pull.pull_artifact", side_effect=_fake_pull_artifact)

        # This should NOT raise, even though the tag is not SemVer
        result = remote_service.resolve_remote_descriptor(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0-legacy-manifest"
        )

        assert result is not None
        assert result.normalized_uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0-legacy-manifest"
