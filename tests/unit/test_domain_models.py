"""Unit tests for domain/models.py."""

from margot.domain.models import PackageType, artifact_type_to_package_type


class TestArtifactTypeToPackageType:
    """Tests for artifact_type_to_package_type()."""

    def test_margo_artifact_type(self) -> None:
        """Should map margo artifactType to PackageType.MARGO."""
        result = artifact_type_to_package_type("application/vnd.margo.app.v1+json")
        assert result == PackageType.MARGO

    def test_compose_artifact_type(self) -> None:
        """Should map compose artifactType to PackageType.COMPOSE."""
        result = artifact_type_to_package_type("application/vnd.org.margo.component.compose+json")
        assert result == PackageType.COMPOSE

    def test_quadlet_artifact_type(self) -> None:
        """Should map quadlet artifactType to PackageType.QUADLET."""
        result = artifact_type_to_package_type("application/vnd.org.margo.component.quadlet+json")
        assert result == PackageType.QUADLET

    def test_unknown_artifact_type(self) -> None:
        """Should return PackageType.UNKNOWN for an unrecognised artifactType."""
        result = artifact_type_to_package_type("something/unknown")
        assert result == PackageType.UNKNOWN

    def test_none_returns_unknown(self) -> None:
        """Should return PackageType.UNKNOWN when artifactType is None."""
        result = artifact_type_to_package_type(None)
        assert result == PackageType.UNKNOWN
