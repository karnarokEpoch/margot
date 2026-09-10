"""Unit tests for services/package.py."""

from pytest import fixture, raises

from margot.domain.models import PackageType
from margot.services import package as package_service


@fixture
def mock_package_metadata(mocker):
    """Mock MargoYaml loader to provide test metadata."""
    mock_meta = mocker.MagicMock()
    mock_meta.name = "testapp"
    mock_meta.version = "1.0.0"
    mock_meta.directory = "margo"
    mock_meta.repository = "public.ecr.aws/g2n4p2m7/margo"
    mock_meta.compose = None
    mock_meta.quadlet = None
    mocker.patch("margot.services.package.load_margo_yaml", return_value=mock_meta)
    return mock_meta


class TestResolveBundleTypes:
    """Tests for _resolve_bundle_types()."""

    def test_bundle_type_returns_margo_only(self, mock_package_metadata):
        """BUNDLE type should return just MARGO to start."""
        result = package_service._resolve_bundle_types(PackageType.BUNDLE, mock_package_metadata)
        assert result == {PackageType.MARGO}

    def test_margo_type_returns_margo(self, mock_package_metadata):
        """Explicit MARGO type should return MARGO."""
        result = package_service._resolve_bundle_types(PackageType.MARGO, mock_package_metadata)
        assert result == {PackageType.MARGO}

    def test_compose_type_requires_defined(self, mock_package_metadata):
        """COMPOSE type should fail if not defined in margo.yaml."""
        mock_package_metadata.compose = None
        with raises(ValueError, match=r"compose component not defined in margo\.yaml"):
            package_service._resolve_bundle_types(PackageType.COMPOSE, mock_package_metadata)

    def test_compose_type_when_defined(self, mock_package_metadata):
        """COMPOSE type should return COMPOSE when defined."""
        mock_compose = type("obj", (object,), {"repository": None})()
        mock_package_metadata.compose = mock_compose
        result = package_service._resolve_bundle_types(PackageType.COMPOSE, mock_package_metadata)
        assert result == {PackageType.COMPOSE}

    def test_quadlet_type_requires_defined(self, mock_package_metadata):
        """QUADLET type should fail if not defined in margo.yaml."""
        mock_package_metadata.quadlet = None
        with raises(ValueError, match=r"quadlet component not defined in margo\.yaml"):
            package_service._resolve_bundle_types(PackageType.QUADLET, mock_package_metadata)

    def test_quadlet_type_when_defined(self, mock_package_metadata):
        """QUADLET type should return QUADLET when defined."""
        mock_quadlet = type("obj", (object,), {"repository": None})()
        mock_package_metadata.quadlet = mock_quadlet
        result = package_service._resolve_bundle_types(PackageType.QUADLET, mock_package_metadata)
        assert result == {PackageType.QUADLET}


class TestResolveComponentRepository:
    """Tests for _resolve_component_repository()."""

    def test_component_repo_takes_precedence(self):
        """Component-level repository should take precedence over global."""
        result = package_service._resolve_component_repository(
            "public.ecr.aws/comp/path",
            "public.ecr.aws/global/path",
        )
        assert result == "comp/path"

    def test_global_repo_used_as_fallback(self):
        """Global repository should be used when component repo is None."""
        result = package_service._resolve_component_repository(
            None,
            "public.ecr.aws/global/path",
        )
        assert result == "global/path"

    def test_fails_with_no_repo(self):
        """Should fail if neither component nor global repo is available."""
        with raises(ValueError, match="No repository configured"):
            package_service._resolve_component_repository(None, None)

    def test_fails_with_invalid_repo_format(self):
        """Should fail if repository doesn't contain a slash."""
        with raises(ValueError, match="Cannot parse repository"):
            package_service._resolve_component_repository("invalid_no_slash", None)


class TestGetBuiltComponentVersions:
    """Tests for _get_built_component_versions()."""

    def test_finds_component_tarballs(self, tmp_path):
        """Should find all component tarballs in build directory."""
        build_dir = tmp_path / ".dist" / "1.0.0"
        build_dir.mkdir(parents=True)
        (build_dir / "testapp-1.0.0.tgz").touch()
        (build_dir / "testapp-1.0.0_variant1.tgz").touch()
        (build_dir / "testapp-1.0.0_variant2.tgz").touch()
        (build_dir / "other-file.txt").touch()

        result = package_service._get_built_component_versions(str(tmp_path / ".dist"), "1.0.0", "compose", "testapp")

        assert len(result) == 3
        assert "1.0.0" in result
        assert "1.0.0_variant1" in result
        assert "1.0.0_variant2" in result

    def test_returns_empty_when_no_builds(self, tmp_path):
        """Should return empty list when build directory doesn't exist."""
        build_dir = tmp_path / ".dist"
        result = package_service._get_built_component_versions(str(build_dir), "1.0.0", "compose", "testapp")
        assert result == []

    def test_sorts_versions(self, tmp_path):
        """Should return sorted version list."""
        build_dir = tmp_path / ".dist" / "1.0.0"
        build_dir.mkdir(parents=True)
        (build_dir / "testapp-1.0.0_z.tgz").touch()
        (build_dir / "testapp-1.0.0_a.tgz").touch()
        (build_dir / "testapp-1.0.0.tgz").touch()

        result = package_service._get_built_component_versions(str(tmp_path / ".dist"), "1.0.0", "compose", "testapp")

        assert result == ["1.0.0", "1.0.0_a", "1.0.0_z"]
