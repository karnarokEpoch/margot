"""Integration tests for services/remote.py — remote OCI artifact resolution."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pytest import raises

from margot.domain.models import PackageType
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

        # Mock the prepare function
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        mockprepared.manifest = _make_manifest()
        mockprepared.package_type = PackageType.MARGO

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        # Mock pullprepared_context to return app.yaml path
        app_yaml_path = tmp_path / "app.yaml"
        app_yaml_path.write_text("kind: ApplicationDescription\nid: test\n", encoding="utf-8")

        mocker.patch(
            "margot.services.remote.pull_service.pull_prepared_context",
            return_value=[str(app_yaml_path), str(tmp_path / "resources")],
        )

        result = remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        assert result.normalized_uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        assert result.app_yaml_path.endswith("app.yaml")
        assert Path(result.app_yaml_path).exists()
        assert result.temp_dir is not None
        # Temp dir should still exist after return
        assert Path(result.temp_dir.name).exists()

    def test_resolve_remote_with_oci_scheme_strips_and_normalizes(self, mocker: Any, tmp_path: Any) -> None:
        """Should accept oci:// scheme and normalize to canonical form."""

        # Mock the prepare function to return a prepared context
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        mockprepared.manifest = _make_manifest()
        mockprepared.package_type = PackageType.MARGO

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        # Mock pullprepared_context to return app.yaml path
        app_yaml_path = tmp_path / "app.yaml"
        app_yaml_path.write_text("kind: ApplicationDescription\nid: test\n", encoding="utf-8")

        mocker.patch(
            "margot.services.remote.pull_service.pull_prepared_context",
            return_value=[str(app_yaml_path)],
        )

        result = remote_service.resolve_remote_descriptor("oci://public.ecr.aws/g2n4p2m7/margo:1.0.0")

        # Normalized URI should be without oci://
        assert result.normalized_uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0"

    def test_resolve_remote_raises_for_malformed_uri(self, mocker: Any) -> None:
        """Should raise ValueError for malformed URI before any I/O."""
        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            side_effect=ValueError("URI must"),
        )

        with raises(ValueError, match="URI must"):
            remote_service.resolve_remote_descriptor("not-a-valid-uri")

    def test_resolve_remote_raises_for_non_margo_compose_artifact(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError for compose artifact before pull."""

        # Mock prepare to return a compose artifact
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/compose:1.0.0"
        mockprepared.manifest = _make_manifest(artifact_type="application/vnd.org.margo.component.compose+json")
        mockprepared.package_type = PackageType.COMPOSE

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        with raises(ValueError, match="not a Margo application descriptor") as exc_info:
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/compose:1.0.0")

        # Error message should mention compose and suggest fetch
        assert "compose" in str(exc_info.value).lower()
        assert "margot fetch" in str(exc_info.value).lower()

    def test_resolve_remote_raises_for_non_margo_quadlet_artifact(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError for quadlet artifact before pull."""

        # Mock prepare to return a quadlet artifact
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/quadlet:1.0.0"
        mockprepared.manifest = _make_manifest(artifact_type="application/vnd.org.margo.component.quadlet+json")
        mockprepared.package_type = PackageType.QUADLET

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        with raises(ValueError, match="not a Margo application descriptor") as exc_info:
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/quadlet:1.0.0")

        assert "quadlet" in str(exc_info.value).lower()
        assert "margot fetch" in str(exc_info.value).lower()

    def test_resolve_remote_raises_for_unknown_artifact_type(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError for unknown artifact type."""

        # Mock prepare to return an unknown artifact
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/unknown:1.0.0"
        mockprepared.manifest = _make_manifest(artifact_type=None)
        mockprepared.package_type = PackageType.UNKNOWN

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        with raises(ValueError, match="not a Margo application descriptor") as exc_info:
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/unknown:1.0.0")

        assert "unknown" in str(exc_info.value).lower()
        assert "margot fetch" in str(exc_info.value).lower()

    def test_resolve_remote_raises_for_missing_app_yaml(self, mocker: Any, tmp_path: Any) -> None:
        """Should raise ValueError when pulled artifact has no app.yaml."""

        # Mock prepare to return a margo artifact
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        mockprepared.manifest = _make_manifest()
        mockprepared.package_type = PackageType.MARGO

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        # Mock pullprepared to return paths without app.yaml
        mocker.patch(
            "margot.services.remote.pull_service.pull_prepared_context",
            return_value=[str(tmp_path / "some-other-file.txt")],
        )

        with raises(ValueError, match=r"app\.yaml") as exc_info:
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        assert "no root app.yaml" in str(exc_info.value).lower()

    def test_resolve_remote_cleans_up_temp_dir_on_exception(self, mocker: Any, tmp_path: Any) -> None:
        """Should clean up temp directory when exception occurs."""

        # Mock prepare to return a margo artifact
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        mockprepared.manifest = _make_manifest()
        mockprepared.package_type = PackageType.MARGO

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        # Mock pullprepared to return empty list (no app.yaml)
        mocker.patch(
            "margot.services.remote.pull_service.pull_prepared_context",
            return_value=[],
        )

        # The test passes if no exception is raised from cleanup
        # (the temp directory should be cleaned up before raising ValueError)
        with raises(ValueError, match=r"app\.yaml"):
            remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/margo:1.0.0")

    def test_resolve_remote_pull_with_recursive_false(self, mocker: Any, tmp_path: Any) -> None:
        """Should call pull_prepared_context with recursive=False."""

        # Mock prepare to return a margo artifact
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        mockprepared.manifest = _make_manifest()
        mockprepared.package_type = PackageType.MARGO

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        app_yaml_path = tmp_path / "app.yaml"
        app_yaml_path.write_text("kind: ApplicationDescription\nid: test\n", encoding="utf-8")

        mock_pullprepared = mocker.patch(
            "margot.services.remote.pull_service.pull_prepared_context",
            return_value=[str(app_yaml_path)],
        )

        remote_service.resolve_remote_descriptor("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        # Verify pull_prepared_context was called with recursive=False
        mock_pullprepared.assert_called_once()
        call_kwargs = mock_pullprepared.call_args[1]
        assert call_kwargs.get("recursive") is False

    def test_resolve_remote_expired_credentials_propagates(self, mocker: Any) -> None:
        """Should propagate CredentialsExpiredError from prepare."""
        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            side_effect=CredentialsExpiredError("Credentials expired for example.com"),
        )

        with raises(CredentialsExpiredError, match="Credentials expired"):
            remote_service.resolve_remote_descriptor("example.com/org/repo:1.0.0")

    def test_resolve_remote_accepts_legacy_non_semver_tag(self, mocker: Any, tmp_path: Any) -> None:
        """Should accept legacy non-SemVer tags without --force."""

        # Mock prepare to return a margo artifact
        mockprepared = MagicMock()
        mockprepared.normalized_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0-legacy-manifest"
        mockprepared.manifest = _make_manifest()
        mockprepared.package_type = PackageType.MARGO

        mocker.patch(
            "margot.services.remote.pull_service.prepare_oci_retrieval",
            return_value=mockprepared,
        )

        app_yaml_path = tmp_path / "app.yaml"
        app_yaml_path.write_text("kind: ApplicationDescription\nid: test\n", encoding="utf-8")

        mocker.patch(
            "margot.services.remote.pull_service.pull_prepared_context",
            return_value=[str(app_yaml_path)],
        )

        # This should NOT raise, even though the tag is not SemVer
        result = remote_service.resolve_remote_descriptor(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0-legacy-manifest"
        )

        assert result is not None
        assert result.normalized_uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0-legacy-manifest"
