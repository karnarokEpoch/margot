"""Integration tests for services/package.py."""

from pathlib import Path
import tarfile

from pytest import fixture, raises

from margot.domain.models import PackageType
from margot.services import build as build_service
from margot.services import package as package_service


@fixture
def fake_project_with_different_versions(tmp_path: Path) -> Path:
    """Create a test project where margo, compose, and quadlet have different versions.

    Reproduces the real-world bug where a project has:
    - margo version: 1.0.2
    - quadlet version: 1.0.2_mosquitto-quadlet (different from margo)
    """
    # Create margo.yaml with different versions for each component
    margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.2
repository: public.ecr.aws/g2n4p2m7/testapp
compose:
  directory: compose
  version: 1.0.2_testapp-compose
  repository: public.ecr.aws/g2n4p2m7/compose
quadlet:
  directory: quadlet
  version: 1.0.2_testapp-quadlet
"""
    (tmp_path / "margo.yaml").write_text(margo_yaml_content)

    # Create margo component
    margo_dir = tmp_path / "margo"
    margo_dir.mkdir()
    (margo_dir / "app.yaml").write_text("name: testapp\nversion: 1.0.2\n")
    (margo_dir / "resources").mkdir()
    (margo_dir / "resources" / "description.md").write_text("# Test App\n")

    # Create compose component
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    (compose_dir / "compose.yaml").write_text("version: '3'\nservices:\n  app: test\n")

    # Create quadlet component
    quadlet_dir = tmp_path / "quadlet"
    quadlet_dir.mkdir()
    (quadlet_dir / "app.container").write_text("[Container]\nImage=test:1.0.2\n")

    # Build all components
    build_service.build(PackageType.ALL, project_dir=str(tmp_path), build_dir=str(tmp_path / ".dist"))

    return tmp_path


@fixture
def fake_project_with_variant_versions(tmp_path: Path) -> Path:
    """Create a test project with variant components at different versions.

    Tests the variant version resolution path where margo version differs from
    per-variant component versions.
    """
    # Create margo.yaml with variant components
    margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.2
repository: public.ecr.aws/g2n4p2m7/testapp
quadlet:
  directory: quadlet
  version: 1.0.2
  variants:
    - name: prod
      version: 1.0.2_prod-variant
    - name: dev
      version: 1.0.2_dev-variant
"""
    (tmp_path / "margo.yaml").write_text(margo_yaml_content)

    # Create margo component
    margo_dir = tmp_path / "margo"
    margo_dir.mkdir()
    (margo_dir / "app.yaml").write_text("name: testapp\nversion: 1.0.2\n")

    # Create quadlet component with variants
    quadlet_dir = tmp_path / "quadlet"
    quadlet_dir.mkdir()

    # Prod variant
    prod_dir = quadlet_dir / "prod"
    prod_dir.mkdir()
    (prod_dir / "app.container").write_text("[Container]\nImage=test:1.0.2-prod\n")

    # Dev variant
    dev_dir = quadlet_dir / "dev"
    dev_dir.mkdir()
    (dev_dir / "app.container").write_text("[Container]\nImage=test:1.0.2-dev\n")

    # Build all components
    build_service.build(PackageType.ALL, project_dir=str(tmp_path), build_dir=str(tmp_path / ".dist"))

    return tmp_path


@fixture
def fake_project_with_all_components(tmp_path: Path) -> Path:
    """Create a test project with margo, compose, and quadlet components already built."""
    # Create margo.yaml
    margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/testapp
compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/compose
quadlet:
  directory: quadlet
  version: 1.0.0
"""
    (tmp_path / "margo.yaml").write_text(margo_yaml_content)

    # Create margo component
    margo_dir = tmp_path / "margo"
    margo_dir.mkdir()
    (margo_dir / "app.yaml").write_text("name: testapp\nversion: 1.0.0\n")
    (margo_dir / "resources").mkdir()
    (margo_dir / "resources" / "description.md").write_text("# Test App\n")

    # Create compose component
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    (compose_dir / "compose.yaml").write_text("version: '3'\nservices:\n  app: test\n")

    # Create quadlet component
    quadlet_dir = tmp_path / "quadlet"
    quadlet_dir.mkdir()
    (quadlet_dir / "app.container").write_text("[Container]\nImage=test:1.0.0\n")

    # Build all components
    build_service.build(PackageType.ALL, project_dir=str(tmp_path), build_dir=str(tmp_path / ".dist"))

    return tmp_path


class TestPackageDifferentVersions:
    """Tests for packaging components with different versions (regression for the bug)."""

    def test_different_component_versions_builds_correctly(self, fake_project_with_different_versions: Path) -> None:
        """Should confirm the build produces separate .dist/<version>/ folders.

        This validates that the fixture reproduces the real scenario before testing package().
        """
        project = fake_project_with_different_versions
        dist_dir = project / ".dist"

        # Verify margo built to its own version folder
        margo_build = dist_dir / "1.0.2" / "margo"
        assert margo_build.exists(), f"Margo should be built at {margo_build}"

        # Verify compose built to its own (different) version folder
        compose_tgz = dist_dir / "1.0.2_testapp-compose" / "testapp-1.0.2_testapp-compose.tgz"
        assert (
            compose_tgz.exists()
        ), f"Compose should be built at {compose_tgz}, not mixed with margo's 1.0.2 folder"

        # Verify quadlet built to its own (different) version folder
        quadlet_tgz = dist_dir / "1.0.2_testapp-quadlet" / "testapp-1.0.2_testapp-quadlet.tgz"
        assert (
            quadlet_tgz.exists()
        ), f"Quadlet should be built at {quadlet_tgz}, not mixed with margo's 1.0.2 folder"

    def test_package_with_different_component_versions(self, fake_project_with_different_versions: Path) -> None:
        """Should package successfully when compose/quadlet versions differ from margo's.

        Regression test for the bug where package.py failed to find compose/quadlet
        output because it looked in the wrong .dist/<version>/ folder.
        """
        project = fake_project_with_different_versions
        bundle_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(project),
            build_dir=str(project / ".dist"),
        )

        assert Path(bundle_path).exists()
        assert bundle_path.endswith(".tgz")

        # Extract and verify structure
        with tarfile.open(bundle_path, "r:gz") as tar:
            members = tar.getnames()
            # Margo content (bundle root uses margo's version 1.0.2)
            assert any("testapp-1.0.2/app.yaml" in m for m in members)
            assert any("testapp-1.0.2/resources/description.md" in m for m in members)
            # Component tarballs should be present (from their own version folders)
            assert any("compose" in m and ".tgz" in m for m in members), "Compose tarball should be in bundle"
            assert any("quadlet" in m and ".tgz" in m for m in members), "Quadlet tarball should be in bundle"

    def test_variant_component_different_versions(self, fake_project_with_variant_versions: Path) -> None:
        """Should package correctly with variant components at different versions.

        Tests that the variant version resolution path also correctly locates
        each variant's build output in its own .dist/<variant_version>/ folder.
        """
        project = fake_project_with_variant_versions
        dist_dir = project / ".dist"

        # Verify margo built to its version folder
        margo_build = dist_dir / "1.0.2" / "margo"
        assert margo_build.exists(), f"Margo should be at {margo_build}"

        # Verify each variant built to its own version folder
        prod_tgz = dist_dir / "1.0.2_prod-variant" / "testapp-1.0.2_prod-variant.tgz"
        dev_tgz = dist_dir / "1.0.2_dev-variant" / "testapp-1.0.2_dev-variant.tgz"
        assert prod_tgz.exists(), f"Prod variant should be at {prod_tgz}"
        assert dev_tgz.exists(), f"Dev variant should be at {dev_tgz}"

        # Package should succeed
        bundle_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(project),
            build_dir=str(project / ".dist"),
        )

        assert Path(bundle_path).exists()

        # Extract and verify both variants are present
        with tarfile.open(bundle_path, "r:gz") as tar:
            members = tar.getnames()
            # Margo content
            assert any("testapp-1.0.2/app.yaml" in m for m in members)
            # Both variant tarballs should be present
            variant_tarballs = [m for m in members if "testapp-1.0.2_" in m and ".tgz" in m]
            assert len(variant_tarballs) >= 2, f"Should have both variant tarballs, got: {variant_tarballs}"


class TestPackageMargo:
    """Tests for packaging margo component."""

    def test_package_margo_only(self, fake_project_with_all_components: Path) -> None:
        """Should package margo component only."""
        project = fake_project_with_all_components
        bundle_path = package_service.package(
            PackageType.MARGO,
            project_dir=str(project),
            build_dir=str(project / ".dist"),
        )

        assert Path(bundle_path).exists()
        assert bundle_path.endswith(".tgz")

        # Extract and verify structure
        with tarfile.open(bundle_path, "r:gz") as tar:
            members = tar.getnames()
            assert any("testapp-1.0.0/app.yaml" in m for m in members)
            assert any("testapp-1.0.0/resources/description.md" in m for m in members)
            # Compose/quadlet should not be present
            assert not any("compose" in m.lower() for m in members)
            assert not any("quadlet" in m.lower() for m in members)

    def test_package_default_includes_all_found(self, fake_project_with_all_components: Path) -> None:
        """Should package all components when no --type specified."""
        project = fake_project_with_all_components
        bundle_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(project),
            build_dir=str(project / ".dist"),
        )

        assert Path(bundle_path).exists()

        # Extract and verify structure
        with tarfile.open(bundle_path, "r:gz") as tar:
            members = tar.getnames()
            # Margo content
            assert any("testapp-1.0.0/app.yaml" in m for m in members)
            assert any("testapp-1.0.0/resources/description.md" in m for m in members)
            # Component directories (without registry prefix, just the repo path)
            assert any("g2n4p2m7/compose/" in m for m in members)
            assert any("g2n4p2m7/testapp/" in m for m in members)


class TestPackageErrors:
    """Tests for error conditions in packaging."""

    def test_missing_build_output_fails(self, tmp_path: Path) -> None:
        """Should fail if build output doesn't exist."""
        (tmp_path / "margo.yaml").write_text(
            "apiVersion: v1\nid: test\nname: test\ndescription: test\nversion: 1.0.0\n"
        )

        with raises(ValueError, match="Built margo artifact not found"):
            package_service.package(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )

    def test_undefined_compose_type_fails(self, tmp_path: Path) -> None:
        """Should fail when requesting compose if not defined in margo.yaml."""
        (tmp_path / "margo.yaml").write_text(
            "apiVersion: v1\nid: test\nname: test\ndescription: test\nversion: 1.0.0\n"
        )
        # Create margo build output
        margo_build = tmp_path / ".dist" / "1.0.0" / "margo"
        margo_build.mkdir(parents=True)
        (margo_build / "app.yaml").write_text("test: true\n")

        with raises(ValueError, match=r"compose component not defined in margo\.yaml"):
            package_service.package(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )

    def test_collision_detection_fails(self, tmp_path: Path) -> None:
        """Should detect and reject colliding component repositories."""
        # Both compose and quadlet with same repository
        margo_yaml_content = """\
apiVersion: v1
id: test
name: test
description: test
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/same
compose:
  directory: compose
  version: 1.0.0
quadlet:
  directory: quadlet
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        # Create build outputs
        build_dir = tmp_path / ".dist" / "1.0.0"
        build_dir.mkdir(parents=True)

        # Margo
        margo_build = build_dir / "margo"
        margo_build.mkdir()
        (margo_build / "app.yaml").write_text("test: true\n")

        # Compose and quadlet tarballs (they'd have the same name if in same version)
        (build_dir / "test-1.0.0.tgz").write_text("compose_content")

        with raises(ValueError, match="Collision:"):
            package_service.package(
                PackageType.BUNDLE,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )

    def test_output_override_works(self, fake_project_with_all_components: Path) -> None:
        """Should respect --output override path."""
        project = fake_project_with_all_components
        custom_output = project / "custom" / "bundle.tgz"

        bundle_path = package_service.package(
            PackageType.MARGO,
            project_dir=str(project),
            build_dir=str(project / ".dist"),
            output=str(custom_output),
        )

        assert bundle_path == str(custom_output)
        assert Path(bundle_path).exists()


class TestBundleStructure:
    """Tests for verifying correct bundle internal structure."""

    def test_margo_resources_preserved_recursively(self, tmp_path: Path) -> None:
        """Should preserve nested directories like resources/ inside the bundle."""
        # Create margo.yaml
        (tmp_path / "margo.yaml").write_text(
            "apiVersion: v1\nid: test\nname: test\ndescription: test\nversion: 1.0.0\n"
        )

        # Create margo with nested resources
        margo_src = tmp_path / "margo"
        margo_src.mkdir()
        (margo_src / "app.yaml").write_text("test: true\n")
        (margo_src / "resources").mkdir()
        (margo_src / "resources" / "file1.md").write_text("# File 1\n")
        (margo_src / "resources" / "subdir").mkdir()
        (margo_src / "resources" / "subdir" / "file2.md").write_text("# File 2\n")

        # Build
        build_service.build(
            PackageType.MARGO,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        # Package
        bundle_path = package_service.package(
            PackageType.MARGO,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        # Extract and verify
        with tarfile.open(bundle_path, "r:gz") as tar:
            members = tar.getnames()
            # Check that nested structure is preserved
            assert any("test-1.0.0/app.yaml" in m for m in members)
            assert any("test-1.0.0/resources/file1.md" in m for m in members)
            assert any("test-1.0.0/resources/subdir/file2.md" in m for m in members)
