"""Unit tests for services/package.py image discovery and inclusion."""

import tarfile
from typing import Any

from pytest import fixture, raises
from typer._click.exceptions import Exit

from margot.domain.models import PackageType
from margot.infra.credentials import CredentialsExpiredError
from margot.infra.oci import OciRegistryError
from margot.services import package as package_service


@fixture
def mock_package_metadata(mocker: Any):
    """Mock MargoYaml loader to provide test metadata."""
    mock_meta = mocker.MagicMock()
    mock_meta.name = "testapp"
    mock_meta.version = "1.0.0"
    mock_meta.id = "com-test-app"
    mock_meta.directory = "margo"
    mock_meta.repository = "public.ecr.aws/g2n4p2m7/margo"
    mock_meta.compose = None
    mock_meta.quadlet = None
    mocker.patch("margot.services.package.load_margo_yaml", return_value=mock_meta)
    return mock_meta


@fixture
def mock_package_metadata_with_image_config(mocker: Any):
    """Mock MargoYaml loader with image configuration enabled."""
    mock_meta = mocker.MagicMock()
    mock_meta.name = "testapp"
    mock_meta.version = "1.0.0"
    mock_meta.id = "com-test-app"
    mock_meta.directory = "margo"
    mock_meta.repository = "public.ecr.aws/g2n4p2m7/margo"

    # Set up compose with image configuration
    mock_compose = mocker.MagicMock()
    mock_compose.version = "1.0.0"  # Compose version
    mock_compose.repository = None  # Use global repo
    mock_compose.image = mocker.MagicMock()
    mock_compose.image.search = "test:1.0.0"
    mock_compose.image.replace = "public.ecr.aws/g2n4p2m7/test:1.0.0"
    mock_compose.variants = ()
    mock_meta.compose = mock_compose
    mock_meta.quadlet = None

    mocker.patch("margot.services.package.load_margo_yaml", return_value=mock_meta)
    return mock_meta


class TestDiscoverImageReferencesCompose:
    """Tests for _discover_image_references_compose()."""

    def test_discovers_single_image_from_compose(self, tmp_path):
        """Should extract a single image reference from compose.yml."""
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()

        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
"""
        (compose_dir / "compose.yml").write_text(compose_content)

        # Create a tarball of the compose content
        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(compose_dir / "compose.yml", arcname="compose.yml")

        refs = package_service._discover_image_references_compose(str(tgz_path))
        assert refs == ["nginx:latest"]

    def test_discovers_multiple_images_from_compose(self, tmp_path):
        """Should extract multiple distinct image references."""
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()

        compose_content = """
version: '3'
services:
  web:
    image: nginx:1.23
  db:
    image: postgres:15
  cache:
    image: redis:7
"""
        (compose_dir / "compose.yml").write_text(compose_content)

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(compose_dir / "compose.yml", arcname="compose.yml")

        refs = package_service._discover_image_references_compose(str(tgz_path))
        assert set(refs) == {"nginx:1.23", "postgres:15", "redis:7"}

    def test_deduplicates_repeated_images(self, tmp_path):
        """Should deduplicate the same image referenced multiple times."""
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()

        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
  web2:
    image: nginx:latest
"""
        (compose_dir / "compose.yml").write_text(compose_content)

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(compose_dir / "compose.yml", arcname="compose.yml")

        refs = package_service._discover_image_references_compose(str(tgz_path))
        assert refs == ["nginx:latest"]

    def test_handles_compose_yaml_file(self, tmp_path):
        """Should read compose.yaml (not just compose.yml)."""
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()

        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
"""
        (compose_dir / "compose.yaml").write_text(compose_content)

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(compose_dir / "compose.yaml", arcname="compose.yaml")

        refs = package_service._discover_image_references_compose(str(tgz_path))
        assert refs == ["nginx:latest"]

    def test_handles_missing_compose_file(self, tmp_path):
        """Should return empty list if no compose.yml/yaml in archive."""
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "some_other_file.txt").write_text("not compose")

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(compose_dir / "some_other_file.txt", arcname="some_other_file.txt")

        refs = package_service._discover_image_references_compose(str(tgz_path))
        assert refs == []

    def test_handles_invalid_yaml(self, tmp_path):
        """Should handle malformed YAML gracefully."""
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()

        compose_content = """
version: '3'
services:
  web
    image: nginx:latest
"""  # Invalid YAML (missing colon after 'web')

        (compose_dir / "compose.yml").write_text(compose_content)

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(compose_dir / "compose.yml", arcname="compose.yml")

        # Should not raise; should return empty list or skip malformed file
        refs = package_service._discover_image_references_compose(str(tgz_path))
        assert refs == []


class TestDiscoverImageReferencesQuadlet:
    """Tests for _discover_image_references_quadlet()."""

    def test_discovers_image_from_container_section(self, tmp_path):
        """Should extract Image= from [Container] sections."""
        quadlet_dir = tmp_path / "quadlet"
        quadlet_dir.mkdir()

        container_content = """
[Unit]
Description=My Container

[Container]
Image=nginx:latest
ContainerName=mycontainer

[Service]
Restart=always
"""
        (quadlet_dir / "app.container").write_text(container_content)

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(quadlet_dir / "app.container", arcname="app.container")

        refs = package_service._discover_image_references_quadlet(str(tgz_path))
        assert refs == ["nginx:latest"]

    def test_discovers_multiple_container_files(self, tmp_path):
        """Should discover images from multiple .container files."""
        quadlet_dir = tmp_path / "quadlet"
        quadlet_dir.mkdir()

        web_content = """
[Container]
Image=nginx:1.23
"""
        db_content = """
[Container]
Image=postgres:15
"""
        (quadlet_dir / "web.container").write_text(web_content)
        (quadlet_dir / "db.container").write_text(db_content)

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(quadlet_dir / "web.container", arcname="web.container")
            tar.add(quadlet_dir / "db.container", arcname="db.container")

        refs = package_service._discover_image_references_quadlet(str(tgz_path))
        assert set(refs) == {"nginx:1.23", "postgres:15"}

    def test_ignores_image_outside_container_section(self, tmp_path):
        """Should ignore Image= outside of [Container] sections."""
        quadlet_dir = tmp_path / "quadlet"
        quadlet_dir.mkdir()

        content = """
Image=wrong:image

[Unit]
Description=My Container
Image=also-wrong:tag

[Container]
Image=correct:image
"""
        (quadlet_dir / "app.container").write_text(content)

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(quadlet_dir / "app.container", arcname="app.container")

        refs = package_service._discover_image_references_quadlet(str(tgz_path))
        assert refs == ["correct:image"]

    def test_ignores_comments(self, tmp_path):
        """Should ignore Image= in comments."""
        quadlet_dir = tmp_path / "quadlet"
        quadlet_dir.mkdir()

        content = """
[Container]
# Image=commented:out
Image=nginx:latest
"""
        (quadlet_dir / "app.container").write_text(content)

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(quadlet_dir / "app.container", arcname="app.container")

        refs = package_service._discover_image_references_quadlet(str(tgz_path))
        assert refs == ["nginx:latest"]

    def test_handles_no_container_files(self, tmp_path):
        """Should return empty list if no .container files."""
        quadlet_dir = tmp_path / "quadlet"
        quadlet_dir.mkdir()
        (quadlet_dir / "other.txt").write_text("not a container file")

        tgz_path = tmp_path / "app-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(quadlet_dir / "other.txt", arcname="other.txt")

        refs = package_service._discover_image_references_quadlet(str(tgz_path))
        assert refs == []


class TestPackageWithImages:
    """Tests for package() function with image inclusion."""

    def test_package_includes_images_by_default(self, tmp_path, mocker: Any, mock_package_metadata):
        """Default behavior should include images."""
        # Setup minimal build structure
        build_dir = tmp_path / ".dist"
        version_dir = build_dir / "1.0.0"
        margo_dir = version_dir / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("kind: ApplicationDescription\napiVersion: v1")

        # Create minimal compose component
        if mock_package_metadata.compose is not None:
            compose_dir = version_dir / "compose"
            compose_dir.mkdir()
            compose_content = """
services:
  web:
    image: nginx:latest
"""
            compose_file = compose_dir / "compose.yml"
            compose_file.write_text(compose_content)

            tgz_path = version_dir / f"{mock_package_metadata.name}-1.0.0.tgz"
            with tarfile.open(tgz_path, "w:gz") as tar:
                tar.add(compose_file, arcname="compose.yml")

        # Mock image pulling/layout creation
        mocker.patch("margot.services.package._discover_image_references_compose", return_value=[])
        mocker.patch("margot.services.package._discover_image_references_quadlet", return_value=[])

        # The default call should have include_images=True
        output_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
        )

        assert output_path.endswith(".tgz")

    def test_package_with_no_images_flag(self, tmp_path, mocker: Any, mock_package_metadata):
        """--no-images should skip image discovery entirely."""
        build_dir = tmp_path / ".dist"
        version_dir = build_dir / "1.0.0"
        margo_dir = version_dir / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("kind: ApplicationDescription")

        # Mock image discovery should NOT be called
        mock_discover_compose = mocker.patch(
            "margot.services.package._discover_image_references_compose"
        )
        mock_discover_quadlet = mocker.patch(
            "margot.services.package._discover_image_references_quadlet"
        )

        output_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
            include_images=False,
        )

        # No image discovery
        mock_discover_compose.assert_not_called()
        mock_discover_quadlet.assert_not_called()
        assert output_path.endswith(".tgz")

    def test_bundle_structure_with_images_folder(self, tmp_path, mocker: Any, mock_package_metadata_with_image_config):
        """Bundle should include images/ folder when include_images=True and image config exists."""
        build_dir = tmp_path / ".dist"
        version_dir = build_dir / "1.0.0"
        margo_dir = version_dir / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("kind: ApplicationDescription")

        # Create a mock compose tarball for discovery
        compose_tgz = version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz") as tar:
            pass  # Empty tarball

        # Mock no images discovered (simpler for this test)
        mocker.patch("margot.services.package._discover_image_references_compose", return_value=[])
        mocker.patch("margot.services.package._discover_image_references_quadlet", return_value=[])

        output_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
            include_images=True,
            runtime="none",
        )

        # Extract and check structure
        assert output_path.endswith(".tgz")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(output_path, "r:gz") as tar:
            tar.extractall(extract_dir, filter="data")

        # Images folder should exist (even if empty since no images discovered) when image config exists
        assert (extract_dir / f"{mock_package_metadata_with_image_config.id}-1.0.0" / "images").exists()

    def test_bundle_no_images_folder_with_no_images_flag(
        self, tmp_path, mocker: Any, mock_package_metadata
    ):
        """Bundle should NOT have images/ folder when include_images=False."""
        build_dir = tmp_path / ".dist"
        version_dir = build_dir / "1.0.0"
        margo_dir = version_dir / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("kind: ApplicationDescription")

        output_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
            include_images=False,
        )

        # Extract and check structure
        assert output_path.endswith(".tgz")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(output_path, "r:gz") as tar:
            tar.extractall(extract_dir, filter="data")

        # Images folder should NOT exist
        assert not (extract_dir / f"{mock_package_metadata.id}-1.0.0" / "images").exists()

    def test_bundle_no_images_folder_without_image_configuration(
        self, tmp_path, mocker: Any, mock_package_metadata
    ):
        """Bundle should NOT have images/ folder when no image configuration exists.

        Regression test for Sprint 9: default package must preserve Item 2's pure archive
        behavior for components without image configuration. No image configuration means
        no image discovery, no credentials, no registry calls, and no images/ directory.
        """
        build_dir = tmp_path / ".dist"
        version_dir = build_dir / "1.0.0"
        margo_dir = version_dir / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("kind: ApplicationDescription")

        # include_images=True (default on), but NO image configuration in margo.yaml
        output_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
            include_images=True,  # default-on, but should be skipped without config
        )

        # Extract and check structure
        assert output_path.endswith(".tgz")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(output_path, "r:gz") as tar:
            tar.extractall(extract_dir, filter="data")

        # Images folder should NOT exist: no image configuration means no image discovery
        assert not (extract_dir / f"{mock_package_metadata.id}-1.0.0" / "images").exists()


class TestImagePullErrors:
    """Tests for error handling during image discovery/pull."""

    def test_discover_and_include_images_credentials_expired(
        self, tmp_path, mocker: Any, mock_package_metadata_with_image_config
    ):
        """Should handle CredentialsExpiredError appropriately and re-raise."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        # Create mock build directory with tarball
        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass  # Empty tarball

        # Mock image discovery to return a full image reference with registry
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )

        # Mock credential check to raise CredentialsExpiredError
        mocker.patch(
            "margot.services.package.check_credentials",
            side_effect=CredentialsExpiredError("docker.io"),
        )

        # Mock console.fatal to raise Exit instead of doing real cleanup
        mocker.patch("margot.services.package.console.fatal", side_effect=Exit(1))

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # The function should exit via console.fatal
        with raises(Exit):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_package_metadata_with_image_config,
                component_versions,
                "none",
            )

    def test_discover_and_include_images_pull_failure_fatal(
        self, tmp_path, mocker: Any, mock_package_metadata_with_image_config
    ):
        """Should report and raise when image pulls fail."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        # Mock image discovery to return a reference
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )

        # Mock credential check to pass
        mocker.patch("margot.services.package.check_credentials")

        # Mock OrasClient initialization
        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)

        # Mock manifest retrieval to fail
        mock_oras.get_manifest.side_effect = OciRegistryError("connection refused")

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Create a mock tarball for discovery
        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass  # Empty

        # Mock discovery to still find images before the pull fails
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )

        # Mock console.fatal to raise Exit (since failed pulls call it)
        mocker.patch("margot.services.package.console.fatal", side_effect=Exit(1))

        # Should raise Exit via console.fatal (for failed pulls)
        with raises(Exit):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_package_metadata_with_image_config,
                component_versions,
                "none",
            )

    def test_has_image_configuration_no_images(self, mock_package_metadata):
        """Should return False when no image configuration exists."""
        result = package_service._has_image_configuration(
            mock_package_metadata,
            {PackageType.MARGO},
        )
        assert result is False

    def test_has_image_configuration_compose_image_set(
        self, mock_package_metadata_with_image_config
    ):
        """Should return True when compose has image configuration."""
        result = package_service._has_image_configuration(
            mock_package_metadata_with_image_config,
            {PackageType.COMPOSE},
        )
        assert result is True

    def test_has_image_configuration_compose_variants_have_image(self, mocker: Any):
        """Should return True when compose variants have image configuration."""
        mock_meta = mocker.MagicMock()
        mock_meta.compose = mocker.MagicMock()
        mock_meta.compose.image = None  # No top-level image
        mock_meta.compose.variants = [
            mocker.MagicMock(image=mocker.MagicMock()),  # Variant has image
        ]
        mock_meta.quadlet = None

        result = package_service._has_image_configuration(
            mock_meta,
            {PackageType.COMPOSE},
        )
        assert result is True

    def test_has_image_configuration_false_when_type_not_included(
        self, mock_package_metadata_with_image_config
    ):
        """Should return False when compose type is not in types_to_include."""
        result = package_service._has_image_configuration(
            mock_package_metadata_with_image_config,
            {PackageType.MARGO},  # COMPOSE not included
        )
        assert result is False
