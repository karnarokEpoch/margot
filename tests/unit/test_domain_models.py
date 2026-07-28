"""Unit tests for domain/models.py."""

from dataclasses import FrozenInstanceError

from pytest import fail

from margot.domain.models import (
    _ARTIFACT_TYPE_MAP,
    BuildTarget,
    PackageType,
    artifact_type_to_package_type,
)


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


class TestPackageTypeAll:
    """Tests for PackageType.ALL."""

    def test_all_exists_and_equals_all(self) -> None:
        """PackageType.ALL should exist and equal 'all'."""
        assert PackageType.ALL == "all"

    def test_all_not_in_artifact_type_map_values(self) -> None:
        """PackageType.ALL should NOT appear in _ARTIFACT_TYPE_MAP.values()."""
        assert PackageType.ALL not in _ARTIFACT_TYPE_MAP.values()


class TestBuildTarget:
    """Tests for BuildTarget dataclass."""

    def test_build_target_construction(self) -> None:
        """BuildTarget should be constructible with all fields."""
        target = BuildTarget(
            package_type=PackageType.MARGO,
            variant_name="my_variant",
            version="1.0.0",
            source_dir="/src",
            output_dir="/out",
        )
        assert target.package_type == PackageType.MARGO
        assert target.variant_name == "my_variant"
        assert target.version == "1.0.0"
        assert target.source_dir == "/src"
        assert target.output_dir == "/out"

    def test_build_target_with_none_variant(self) -> None:
        """BuildTarget should accept variant_name=None."""
        target = BuildTarget(
            package_type=PackageType.COMPOSE,
            variant_name=None,
            version="2.1.0",
            source_dir="/src",
            output_dir="/out",
        )
        assert target.variant_name is None
        assert target.package_type == PackageType.COMPOSE

    def test_build_target_immutable(self) -> None:
        """BuildTarget should be immutable (frozen=True)."""
        target = BuildTarget(
            package_type=PackageType.QUADLET,
            variant_name="test",
            version="0.1.0",
            source_dir="/src",
            output_dir="/out",
        )
        try:
            target.package_type = PackageType.MARGO  # type: ignore[assignment]
            fail("Should have raised FrozenInstanceError")
        except FrozenInstanceError:
            pass  # Expected
