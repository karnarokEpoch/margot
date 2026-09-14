"""Integration tests for prepared OCI retrieval context and shared pull logic."""

from typing import Any
from unittest.mock import MagicMock

from pytest import raises

from margot.domain.models import PackageType
from margot.infra.credentials import CredentialsExpiredError
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


class TestPreparedOCIRetrieval:
    """Tests for prepared OCI retrieval context."""

    def testprepare_oci_retrieval_validates_normalizes_fetches_once(
        self, mocker: Any, tmp_path: Any
    ) -> None:
        """Prepare should normalize URI, validate, check credentials, fetch manifest exactly once."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()

        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.OrasClient", return_value=mock_client)

        # Call prepare with oci:// scheme
        prepared = pull_service.prepare_oci_retrieval("oci://public.ecr.aws/g2n4p2m7/margo:1.0.0")

        # Should normalize URI (strip oci://)
        assert prepared.normalized_uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0"

        # Should extract hostname
        assert prepared.hostname == "public.ecr.aws"

        # Should have the client
        assert prepared.client is mock_client

        # Should have the manifest
        assert prepared.manifest == _make_manifest()

        # Should detect package type
        assert prepared.package_type == PackageType.MARGO

        # get_manifest should be called exactly once
        mock_client.get_manifest.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0")

    def testprepare_oci_retrieval_checks_credentials_once(self, mocker: Any) -> None:
        """Prepare should call credentials.check_credentials exactly once."""
        mock_client = MagicMock()
        mock_client.get_manifest.return_value = _make_manifest()
        mock_check_creds = mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.OrasClient", return_value=mock_client)

        pull_service.prepare_oci_retrieval("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        # Should check credentials for the hostname exactly once
        mock_check_creds.assert_called_once_with("public.ecr.aws")

    def testprepare_oci_retrieval_raises_on_malformed_uri(self, mocker: Any) -> None:
        """Prepare should raise ValueError for malformed URI before any I/O."""
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mock_class = mocker.patch("margot.services.pull.OrasClient")

        with raises(ValueError, match="URI must"):
            pull_service.prepare_oci_retrieval("not-a-valid-uri")

        mock_class.assert_not_called()

    def testprepare_oci_retrieval_raises_on_expired_credentials(self, mocker: Any) -> None:
        """Prepare should propagate CredentialsExpiredError from check_credentials."""
        mocker.patch(
            "margot.services.pull.credentials.check_credentials",
            side_effect=CredentialsExpiredError("Credentials expired for public.ecr.aws"),
        )
        mock_class = mocker.patch("margot.services.pull.OrasClient")

        with raises(CredentialsExpiredError, match="Credentials expired"):
            pull_service.prepare_oci_retrieval("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        mock_class.assert_not_called()

    def testprepare_oci_retrieval_detects_all_artifact_types(self, mocker: Any) -> None:
        """Prepare should detect all PackageType variants via artifact_type_to_package_type."""
        test_cases = [
            ("application/vnd.margo.app.v1+json", PackageType.MARGO),
            ("application/vnd.org.margo.component.compose+json", PackageType.COMPOSE),
            ("application/vnd.org.margo.component.quadlet+json", PackageType.QUADLET),
        ]

        for artifact_type, expected_package_type in test_cases:
            mock_client = MagicMock()
            mock_client.get_manifest.return_value = _make_manifest(artifact_type=artifact_type)
            mocker.patch("margot.services.pull.credentials.check_credentials")
            mocker.patch("margot.services.pull.OrasClient", return_value=mock_client)

            prepared = pull_service.prepare_oci_retrieval("public.ecr.aws/repo:1.0.0")
            assert prepared.package_type == expected_package_type


class TestPullPreparedContext:
    """Tests for pull_prepared_context internal function."""

    def testpull_prepared_context_uses_cached_client(self, mocker: Any, tmp_path: Any) -> None:
        """Pull prepared should use the prepared context's client, not create a new one."""
        mock_client = MagicMock()
        mock_client.pull.return_value = [str(tmp_path / "app.yaml")]
        mock_oras_class = mocker.patch("margot.services.pull.OrasClient", return_value=mock_client)

        prepared = MagicMock()
        prepared.normalized_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        prepared.client = mock_client
        prepared.package_type = PackageType.MARGO
        prepared.manifest = _make_manifest()

        pull_service.pull_prepared_context(prepared, str(tmp_path))

        # Should NOT create a new OrasClient
        mock_oras_class.assert_not_called()

        # Should use the prepared client for pull
        mock_client.pull.assert_called_once()

    def testpull_prepared_context_respects_prepared_manifest(self, mocker: Any, tmp_path: Any) -> None:
        """Pull prepared should use manifest from the prepared context, not fetch again."""
        mock_client = MagicMock()
        mock_client.pull.return_value = [str(tmp_path / "app.yaml")]

        manifest = _make_manifest()
        prepared = MagicMock()
        prepared.normalized_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        prepared.client = mock_client
        prepared.package_type = PackageType.MARGO
        prepared.manifest = manifest

        pull_service.pull_prepared_context(prepared, str(tmp_path))

        # get_manifest should never be called from pull_prepared_context
        # (it's already in the prepared context)
        mock_client.get_manifest.assert_not_called()

    def test_pull_artifact_uses_prepare_and_pull_prepared(self, mocker: Any, tmp_path: Any) -> None:
        """pull_artifact should call prepare_oci_retrieval then pull_prepared_context."""
        mock_prepare = mocker.patch(
            "margot.services.pull.prepare_oci_retrieval",
        )
        mock_pull_prepared = mocker.patch(
            "margot.services.pull.pull_prepared_context",
            return_value=[str(tmp_path / "app.yaml")],
        )

        prepared_context = MagicMock()
        mock_prepare.return_value = prepared_context

        result = pull_service.pull_artifact("public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        # Should prepare first
        mock_prepare.assert_called_once_with("public.ecr.aws/g2n4p2m7/margo:1.0.0")

        # Then pull prepared with kwargs
        mock_pull_prepared.assert_called_once()
        call_args = mock_pull_prepared.call_args
        assert call_args[0] == (prepared_context, str(tmp_path))
        assert call_args[1] == {"force": False, "force_type": None, "recursive": False}

        # And return the result
        assert result == [str(tmp_path / "app.yaml")]

    def test_pull_artifact_still_normalizes_uri(self, mocker: Any, tmp_path: Any) -> None:
        """pull_artifact should normalize URI before passing to prepare."""
        mock_prepare = mocker.patch("margot.services.pull.prepare_oci_retrieval")
        mocker.patch("margot.services.pull.pull_prepared_context", return_value=[])

        prepared_context = MagicMock()
        mock_prepare.return_value = prepared_context

        pull_service.pull_artifact("oci://public.ecr.aws/g2n4p2m7/margo:1.0.0", outdir=str(tmp_path))

        # Should call prepare with normalized URI
        call_args = mock_prepare.call_args[0]
        assert call_args[0] == "oci://public.ecr.aws/g2n4p2m7/margo:1.0.0"

    def test_pull_artifact_preserves_force_and_recursive_flags(self, mocker: Any, tmp_path: Any) -> None:
        """pull_artifact flags (force, recursive) should be passed through correctly."""
        mock_prepare = mocker.patch("margot.services.pull.prepare_oci_retrieval")
        mock_pull_prepared = mocker.patch("margot.services.pull.pull_prepared_context", return_value=[])

        prepared_context = MagicMock()
        prepared_context.package_type = PackageType.MARGO
        mock_prepare.return_value = prepared_context

        pull_service.pull_artifact(
            "public.ecr.aws/g2n4p2m7/margo:1.0.0",
            outdir=str(tmp_path),
            force=True,
            recursive=True,
        )

        # Verify flags were included in the pull_prepared call
        call_kwargs = mock_pull_prepared.call_args[1]
        assert call_kwargs.get("force") is True
        assert call_kwargs.get("recursive") is True
