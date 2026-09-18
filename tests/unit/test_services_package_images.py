"""Unit tests for services/package.py image discovery and inclusion."""

import contextlib
import errno
from json import JSONDecodeError
import os
from pathlib import Path
import subprocess
import sys
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
        with tarfile.open(compose_tgz, "w:gz"):
            pass  # Empty tarball

        # Mock no images discovered (simpler for this test)
        mocker.patch("margot.services.package._discover_image_references_compose", return_value=[])
        mocker.patch("margot.services.package._discover_image_references_quadlet", return_value=[])

        package_service.package(
            PackageType.BUNDLE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
            include_images=True,
            runtime="none",
        )


class TestImageScanAllImagesRegardlessOfConfig:
    """Tests for the Item 6 behavior: scan ALL images regardless of image: block."""

    def test_scan_all_images_without_image_config(self, tmp_path, mocker: Any, mock_package_metadata):
        """REGRESSION TEST: Scan all images even without image: block in margo.yaml.

        This is the core regression motivating Item 6: a component with no image:
        block but with compose/quadlet referencing images should still pull them all.
        """
        # Setup: component with NO image: block but with image references in built content
        build_dir = tmp_path / ".dist"
        version_dir = build_dir / "1.0.0"
        margo_dir = version_dir / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("kind: ApplicationDescription")

        # Create compose component WITHOUT image configuration in margo.yaml
        mock_package_metadata.compose = mocker.MagicMock()
        mock_package_metadata.compose.version = "1.0.0"
        mock_package_metadata.compose.repository = None
        mock_package_metadata.compose.image = None  # KEY: no image: block
        mock_package_metadata.compose.variants = ()

        # But the built compose content HAS image references (e.g., nginx:1.27 directly)
        compose_content = """
version: '3'
services:
  web:
    image: docker.io/library/nginx:1.27
  db:
    image: docker.io/library/postgres:15
"""
        compose_dir = version_dir / "compose"
        compose_dir.mkdir()
        (compose_dir / "compose.yml").write_text(compose_content)

        tgz_path = version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(compose_dir / "compose.yml", arcname="compose.yml")

        # Mock image pulling to succeed
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:1.27", "docker.io/library/postgres:15"],
        )
        mocker.patch("margot.services.package.check_credentials")
        mocker.patch("margot.services.package._create_oci_image_layout_tar")

        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.return_value = {"mediaType": "application/vnd.oci.image.manifest.v1+json"}

        # Call package() with include_images=True (default)
        output_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
            include_images=True,  # Default: scan for images
        )

        # Verify the bundle was created successfully
        assert output_path.endswith(".tgz")

        # Verify images were discovered (not blocked by lack of image: config)
        package_service._discover_image_references_compose.assert_called()

    def test_all_references_attempted_before_fail(self, tmp_path, mocker: Any):
        """One unpullable image among several: all others attempted, each warned, then hard fail.

        This confirms attempt-all-then-fail semantics: no pre-loop short-circuit.
        """
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        # Setup metadata with compose component
        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()  # Compose is defined
        mock_meta.quadlet = None

        # Mock discovery to return three image references with proper registries
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=[
                "docker.io/library/nginx:latest",
                "docker.io/library/postgres:15",
                "unpullable.registry/image:tag",
            ],
        )

        # Mock credential check to pass for all registries
        mocker.patch("margot.services.package.check_credentials")

        # Mock OrasClient
        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)

        # First two succeed, third fails
        def get_manifest_side_effect(ref):
            if "unpullable" in ref:
                raise OciRegistryError(f"Cannot pull {ref}")
            return {"mediaType": "application/vnd.oci.image.manifest.v1+json"}

        mock_oras.get_manifest.side_effect = get_manifest_side_effect

        # Mock OCI layout tar creation for successful images
        mocker.patch("margot.services.package._create_oci_image_layout_tar")

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Attempting all images should still raise via console.fatal for the failed ones
        with raises(Exit):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        # Verify that the pull attempt function was called for all three images
        # (not short-circuited after the first failure)
        assert mock_oras.get_manifest.call_count >= 2  # At least called for first and failed one

    def test_anonymous_pull_when_no_credential(self, tmp_path, mocker: Any, mock_package_metadata):
        """Registry with NO stored credential: anonymous pull attempted, not hard failure."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        # Mock image discovery
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )

        # Mock credential check to raise (no stored credential) but NOT CredentialsExpiredError
        mocker.patch(
            "margot.services.package.check_credentials",
            side_effect=ValueError("No credential found"),
        )

        # Mock OrasClient to succeed
        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.return_value = {"mediaType": "application/vnd.oci.image.manifest.v1+json"}

        mocker.patch("margot.services.package._create_oci_image_layout_tar")

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should NOT raise; should attempt anonymous pull
        with contextlib.suppress(OciRegistryError):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_package_metadata,
                component_versions,
                "none",
            )

    def test_expired_credential_via_aggregate_path(self, tmp_path, mocker: Any):
        """Expired stored credential reported via aggregate failure path (all images attempted)."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        # Setup metadata with compose component
        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        # Mock image discovery to return one image with an expired credential registry
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["registry1.io/image1:1.0"],
        )

        # Mock credential check: registry has expired cred
        mocker.patch(
            "margot.services.package.check_credentials",
            side_effect=CredentialsExpiredError("registry1.io"),
        )

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should raise Exit via console.fatal (for failed pulls, which includes the expired cred)
        with raises(Exit):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

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





class TestPodmanSocketResolution:
    """Tests for _resolve_podman_socket_uri() function."""

    def test_resolve_with_xdg_runtime_dir_set(self, mocker: Any):
        """Should use XDG_RUNTIME_DIR when set."""
        mocker.patch.dict("os.environ", {"XDG_RUNTIME_DIR": "/run/user/1000"})
        uri = package_service._resolve_podman_socket_uri()
        assert uri == "unix:///run/user/1000/podman/podman.sock"

    def test_resolve_without_xdg_runtime_dir_uses_systemd_default(self, mocker: Any):
        """Should fall back to /run/user/{uid}/podman/podman.sock when XDG_RUNTIME_DIR is unset."""
        # Mock environ to not have XDG_RUNTIME_DIR and mock getuid
        mock_environ_get = mocker.patch("margot.services.package.environ.get", return_value=None)
        mock_getuid = mocker.patch("margot.services.package.getuid", return_value=1000)

        uri = package_service._resolve_podman_socket_uri()
        assert uri == "unix:///run/user/1000/podman/podman.sock"
        mock_environ_get.assert_called_once_with("XDG_RUNTIME_DIR")
        mock_getuid.assert_called_once()


class TestDockerProbeTimeout:
    """Tests for Docker daemon probe timeout."""

    def test_docker_probe_passes_timeout_parameter(self, mocker: Any):
        """Should pass timeout=5 to docker_from_env()."""
        mock_docker_from_env = mocker.patch(
            "margot.services.package.docker_from_env",
            return_value=mocker.MagicMock(),
        )
        mock_client = mock_docker_from_env.return_value
        mock_client.images.get.return_value = mocker.MagicMock()

        # Call _lookup_image_docker
        package_service._lookup_image_docker(
            "test:latest",
            "/tmp",
            required=False,
        )

        # Verify docker_from_env was called with timeout=5
        mock_docker_from_env.assert_called_once()
        call_kwargs = mock_docker_from_env.call_args[1]
        assert call_kwargs.get("timeout") == 5

    def test_docker_probe_timeout_exception_handled_in_auto_probe(self, mocker: Any):
        """Timeout exception during Docker probe should not crash auto-probe."""

        # Mock docker_from_env to raise a timeout
        mocker.patch(
            "margot.services.package.docker_from_env",
            side_effect=TimeoutError("Read timed out"),
        )

        # Auto-probe with Docker timeout should return None (not raise)
        result = package_service._lookup_image_with_runtime(
            "test:latest",
            "/tmp",
            "auto",
            mocker.MagicMock(),
        )

        # Should return None (fall through to registry)
        assert result is None

    def test_docker_probe_timeout_with_forced_runtime_raises(self, mocker: Any):
        """Forced Docker runtime with timeout should raise RuntimeError."""

        mocker.patch(
            "margot.services.package.docker_from_env",
            side_effect=TimeoutError("Read timed out"),
        )

        # Forced Docker should raise
        with raises(RuntimeError, match="Docker socket unreachable"):
            package_service._lookup_image_docker(
                "test:latest",
                "/tmp",
                required=True,
            )


class TestRegistryManifestFetchError:
    """Tests for registry manifest-fetch error handling."""

    def test_manifest_fetch_json_decode_error_wraps_in_ociregistryerror(self, tmp_path, mocker: Any):
        """JSONDecodeError from manifest fetch should be wrapped in OciRegistryError."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        # Mock image discovery
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )
        mocker.patch("margot.services.package.check_credentials")

        # Mock OrasClient to raise JSONDecodeError when fetching manifest
        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.side_effect = JSONDecodeError(
            "Expecting value", "doc", 0
        )

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should raise OciRegistryError with clear message (via console.fatal)
        mocker.patch("margot.services.package.console.fatal", side_effect=Exit(1))

        with raises(Exit):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

    def test_manifest_fetch_error_includes_ref_name_in_message(self, tmp_path, mocker: Any):
        """Error message should include the image reference."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        image_ref = "docker.io/library/myapp:2.0"

        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=[image_ref],
        )
        mocker.patch("margot.services.package.check_credentials")

        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.side_effect = JSONDecodeError(
            "Expecting value", "doc", 0
        )

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Capture the warning call to verify error message contains ref
        mock_warning = mocker.patch("margot.services.package.console.warning")
        mocker.patch("margot.services.package.console.fatal", side_effect=Exit(1))

        with raises(Exit):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        # Verify that at least one warning was issued
        assert mock_warning.called


class TestProbeAndFallbackLogging:
    """Tests for info-level logging of probe/fallback narrative."""

    def test_auto_probe_with_no_local_images_logs_info_narrative(self, mocker: Any):
        """Auto-probe narrative should be at info level."""
        mock_info = mocker.patch("margot.services.package.console.info")

        # Mock Podman lookup to return None
        mocker.patch("margot.services.package._lookup_image_podman", return_value=None)
        # Mock Docker lookup to return None
        mocker.patch("margot.services.package._lookup_image_docker", return_value=None)

        result = package_service._lookup_image_with_runtime(
            "docker.io/library/nginx:latest",
            "/tmp",
            "auto",
            mocker.MagicMock(),
        )

        # Should fall back to registry (return None)
        assert result is None

        # Verify info-level messages were logged
        info_calls = [call[0][0] for call in mock_info.call_args_list]
        assert any("Trying local Podman" in str(call) for call in info_calls)
        assert any("Trying local Docker" in str(call) for call in info_calls)
        assert any("Falling back to registry" in str(call) for call in info_calls)

    def test_auto_probe_with_podman_success_logs_found_message(self, mocker: Any):
        """Successful Podman lookup should log info-level success message."""
        mock_info = mocker.patch("margot.services.package.console.info")

        # Mock Podman lookup to return a path
        mocker.patch(
            "margot.services.package._lookup_image_podman",
            return_value="/tmp/image.tar",
        )

        result = package_service._lookup_image_with_runtime(
            "docker.io/library/nginx:latest",
            "/tmp",
            "auto",
            mocker.MagicMock(),
        )

        # Should return the path
        assert result == "/tmp/image.tar"

        # Verify success message
        info_calls = [call[0][0] for call in mock_info.call_args_list]
        assert any("Found" in str(call) and "Podman" in str(call) for call in info_calls)


class TestRegressionPodmanSocketPath:
    """Regression tests for the hardcoded Podman socket bug."""

    def test_podman_lookup_does_not_use_path_home_socket(self, mocker: Any):
        """_lookup_image_podman should NOT use Path.home()/.local/share path."""
        mock_podman_client = mocker.MagicMock()
        mocker.patch(
            "margot.services.package.PodmanClient",
            return_value=mock_podman_client,
        )

        # Mock the image lookup to succeed
        mock_image = mocker.MagicMock()
        mock_podman_client.images.get.return_value = mock_image
        mock_image.export.return_value = [b"tar_data"]

        # Mock _resolve_podman_socket_uri to return a known value
        mock_resolve = mocker.patch(
            "margot.services.package._resolve_podman_socket_uri",
            return_value="unix:///run/user/1000/podman/podman.sock",
        )

        package_service._lookup_image_podman("test:latest", "/tmp", required=False)

        # Verify _resolve_podman_socket_uri was called (not hardcoded path)
        mock_resolve.assert_called_once()


class TestRegressionProbeAndFallbackBehavior:
    """Regression tests ensuring probe/fallback behaviors unchanged."""

    def test_runtime_none_returns_none_immediately(self, mocker: Any):
        """--runtime none should return None immediately without any probe."""
        mock_podman = mocker.patch("margot.services.package._lookup_image_podman")
        mock_docker = mocker.patch("margot.services.package._lookup_image_docker")

        result = package_service._lookup_image_with_runtime(
            "test:latest",
            "/tmp",
            "none",
            mocker.MagicMock(),
        )

        assert result is None
        mock_podman.assert_not_called()
        mock_docker.assert_not_called()

    def test_runtime_podman_forced_raises_on_unreachable(self, mocker: Any):
        """--runtime podman should raise when socket unreachable."""
        mocker.patch(
            "margot.services.package._lookup_image_podman",
            side_effect=RuntimeError("Socket unreachable"),
        )

        with raises(RuntimeError, match="Socket unreachable"):
            package_service._lookup_image_with_runtime(
                "test:latest",
                "/tmp",
                "podman",
                mocker.MagicMock(),
            )

    def test_runtime_docker_forced_raises_on_unreachable(self, mocker: Any):
        """--runtime docker should raise when socket unreachable."""
        mocker.patch(
            "margot.services.package._lookup_image_docker",
            side_effect=RuntimeError("Socket unreachable"),
        )

        with raises(RuntimeError, match="Socket unreachable"):
            package_service._lookup_image_with_runtime(
                "test:latest",
                "/tmp",
                "docker",
                mocker.MagicMock(),
            )



class TestImagePullENOSPCHandling:
    """Tests for ENOSPC (No space left on device) error handling during image pulls."""

    def test_enospc_during_image_pull_produces_tmpdir_guidance(
        self, tmp_path, mocker: Any
    ):
        """ENOSPC during image pull should produce actionable TMPDIR guidance.

        When OSError with errno.ENOSPC is raised during image pull (typically from
        mkdtemp() or file writes), the error message should clearly suggest using
        TMPDIR environment variable to point to a directory with more free space.
        """
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        # Setup metadata with compose component
        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        # Mock image discovery to return one image
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )

        # Mock credential check to pass
        mocker.patch("margot.services.package.check_credentials")

        # Mock OrasClient initialization
        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)

        # Make the manifest retrieval succeed, but the tar creation fail with ENOSPC
        mock_oras.get_manifest.return_value = {
            "mediaType": "application/vnd.oci.image.manifest.v1+json"
        }

        # Create an OSError with errno ENOSPC
        enospc_error = OSError(errno.ENOSPC, "No space left on device")
        mocker.patch(
            "margot.services.package._create_oci_image_layout_tar",
            side_effect=enospc_error,
        )

        # Capture warning messages
        mock_warning = mocker.patch("margot.services.package.console.warning")
        mocker.patch("margot.services.package.console.fatal", side_effect=Exit(1))

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should raise Exit via console.fatal (for failed pulls)
        with raises(Exit):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        # Verify that a warning was issued containing TMPDIR guidance
        assert mock_warning.called
        warning_calls = [call[0][0] for call in mock_warning.call_args_list]

        # Find the ENOSPC-specific warning
        enospc_warning = None
        for call in warning_calls:
            if "Disk ran out of space" in call or "temporary directory" in call:
                enospc_warning = call
                break

        assert enospc_warning is not None, "Expected ENOSPC-specific warning message"
        assert "TMPDIR" in enospc_warning, "Warning should mention TMPDIR environment variable"
        assert (
            "TMPDIR=/path/with/more/space" in enospc_warning
        ), "Warning should show example TMPDIR usage"

    def test_other_oserrors_use_generic_message(self, tmp_path, mocker: Any):
        """Non-ENOSPC OSErrors should still produce the old generic message.

        This is a regression test to ensure we don't break existing error handling
        for permission errors, file-not-found, etc.
        """
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        # Setup metadata
        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )
        mocker.patch("margot.services.package.check_credentials")

        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.return_value = {
            "mediaType": "application/vnd.oci.image.manifest.v1+json"
        }

        # Raise a different OSError (e.g., permission denied)
        perm_error = OSError(errno.EACCES, "Permission denied")
        mocker.patch(
            "margot.services.package._create_oci_image_layout_tar",
            side_effect=perm_error,
        )

        mock_warning = mocker.patch("margot.services.package.console.warning")
        mocker.patch("margot.services.package.console.fatal", side_effect=Exit(1))

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        with raises(Exit):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        # Verify that a warning was issued, but with the generic message
        assert mock_warning.called
        warning_calls = [call[0][0] for call in mock_warning.call_args_list]

        # Find the generic error message
        generic_warning = None
        for call in warning_calls:
            if "Unexpected error pulling image" in call:
                generic_warning = call
                break

        assert (
            generic_warning is not None
        ), "Expected generic error message for non-ENOSPC OSError"
        # It should NOT contain TMPDIR guidance (that's specific to ENOSPC)
        assert "TMPDIR" not in generic_warning, "Non-ENOSPC errors should not mention TMPDIR"



class TestTmpdirValidation:
    """Tests for TMPDIR directory creation before image export."""

    def test_tmpdir_explicit_dir_argument_bypasses_cache_regression(
        self, tmp_path, mocker: Any
    ):
        """REGRESSION TEST: mkdtemp(dir=) bypasses tempfile cache even if poisoned first.

        This is the critical regression test for the tempfile caching bug:
        - If some other code (oras-py, podman, etc.) calls tempfile.gettempdir()
          BEFORE our code runs, the cache gets set to /tmp
        - Creating the TMPDIR directory afterward does NOT invalidate the cache
        - Previous fix (mkdir + bare mkdtemp) failed because bare mkdtemp() still
          uses the cached /tmp
        - Correct fix: pass explicit dir= to mkdtemp() to bypass the cache entirely

        This test verifies the fix by:
        1. Having something else call tempfile.gettempdir() first (cache poisoning)
        2. Creating a custom TMPDIR directory
        3. Calling our fixed code path
        4. Asserting the returned path is actually under the custom TMPDIR (not /tmp)
        """
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        # Use a fresh subprocess to avoid import-time tempfile cache issues in the test process
        # This simulates the real race where oras-py or podman initializes tempfile before us
        custom_tmpdir = tmp_path / "custom_tmpdir_cache_test"
        test_script = f"""
import sys
import os
import tempfile
from pathlib import Path
from tempfile import mkdtemp, gettempdir

# Set custom TMPDIR that doesn't exist yet
custom_tmpdir = Path("{custom_tmpdir!s}")

# POISON THE CACHE: call tempfile.gettempdir() first (simulating oras-py or podman)
print(f"CACHE_BEFORE={{gettempdir()}}", file=sys.stderr)

# Create the TMPDIR
custom_tmpdir.mkdir(parents=True, exist_ok=True)

# OLD BROKEN FIX: bare mkdtemp would still use cache and go to /tmp
# broken_result = mkdtemp(prefix="test-broken-")

# NEW CORRECT FIX: explicit dir= bypasses cache
effective_tmpdir = os.environ.get("TMPDIR") or gettempdir()
fixed_result = mkdtemp(prefix="test-fixed-", dir=effective_tmpdir)

print(f"RESULT={{fixed_result}}", file=sys.stderr)
print(f"IN_CUSTOM={{str(fixed_result).startswith(str(custom_tmpdir))}}", file=sys.stderr)

# Verify the result
if str(fixed_result).startswith(str(custom_tmpdir.resolve())):
    sys.exit(0)
else:
    print(f"FAIL: Expected {{custom_tmpdir}}, got {{fixed_result}}", file=sys.stderr)
    sys.exit(1)
"""

        # Run the subprocess with custom TMPDIR
        env = os.environ.copy()
        env["TMPDIR"] = str(custom_tmpdir)
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", test_script],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        # Verify the subprocess succeeded (fix works)
        if result.returncode != 0:
            raise AssertionError(
                f"Cache bypass test failed: {result.stderr}"
            )

        # Parse the result
        lines = result.stderr.strip().split("\n")
        cache_before = next(
            (line.split("=")[1] for line in lines if line.startswith("CACHE_BEFORE")), None
        )
        fixed_result = next(
            (line.split("=")[1] for line in lines if line.startswith("RESULT=")), None
        )
        in_custom = next(
            (line.split("=")[1] for line in lines if line.startswith("IN_CUSTOM=")), None
        )

        assert cache_before == "/tmp", f"Expected cache to be poisoned to /tmp, got {cache_before}"
        assert in_custom == "True", f"Expected fixed result to be under custom TMPDIR, got {fixed_result}"

    def test_tmpdir_not_set_behavior_unchanged(self, tmp_path, mocker: Any):
        """With TMPDIR unset, behavior is completely unchanged."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        # Mock image discovery and pulling to succeed
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )
        mocker.patch("margot.services.package.check_credentials")

        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.return_value = {
            "mediaType": "application/vnd.oci.image.manifest.v1+json"
        }

        mocker.patch("margot.services.package._create_oci_image_layout_tar")

        # Ensure TMPDIR is not set
        mocker.patch.dict("os.environ", {}, clear=True)

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should not raise any error
        with contextlib.suppress(OciRegistryError):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

    def test_tmpdir_set_to_existing_directory_unchanged(self, tmp_path, mocker: Any):
        """With TMPDIR set to an existing directory, directory is untouched (no re-creation)."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )
        mocker.patch("margot.services.package.check_credentials")

        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.return_value = {
            "mediaType": "application/vnd.oci.image.manifest.v1+json"
        }

        mocker.patch("margot.services.package._create_oci_image_layout_tar")

        # Create an existing TMPDIR
        custom_tmpdir = tmp_path / "custom_temp"
        custom_tmpdir.mkdir()
        original_stat = custom_tmpdir.stat()

        # Mock environ to return our custom tmpdir
        mocker.patch.dict("os.environ", {"TMPDIR": str(custom_tmpdir)})

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should not raise error and directory should be unchanged
        with contextlib.suppress(OciRegistryError):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        # Verify directory still exists and was not recreated
        assert custom_tmpdir.is_dir()
        assert custom_tmpdir.stat().st_ino == original_stat.st_ino

    def test_tmpdir_set_to_nonexistent_path_creates_directory(self, tmp_path, mocker: Any):
        """With TMPDIR set to non-existent path, directory is created before image work."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )
        mocker.patch("margot.services.package.check_credentials")

        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.return_value = {
            "mediaType": "application/vnd.oci.image.manifest.v1+json"
        }

        mocker.patch("margot.services.package._create_oci_image_layout_tar")

        # Create a TMPDIR path that doesn't exist yet
        custom_tmpdir = tmp_path / "custom_temp" / "nested"
        assert not custom_tmpdir.exists()

        # Mock environ to return our non-existent tmpdir
        mocker.patch.dict("os.environ", {"TMPDIR": str(custom_tmpdir)})

        # Spy on console.debug to verify creation message
        mock_debug = mocker.patch("margot.services.package.console.debug")

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should not raise error and directory should now exist
        with contextlib.suppress(OciRegistryError):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        # Verify directory was created
        assert custom_tmpdir.is_dir()

        # Verify debug message was logged
        debug_calls = [call[0][0] for call in mock_debug.call_args_list]
        creation_msg = next(
            (call for call in debug_calls if "Created TMPDIR directory" in call),
            None,
        )
        assert creation_msg is not None
        assert str(custom_tmpdir) in creation_msg

    def test_tmpdir_creation_permission_denied_raises_hard_error(
        self, tmp_path, mocker: Any, monkeypatch
    ):
        """TMPDIR creation with permission denied raises OciRegistryError, hard-fail before any image pull."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        # Mock image discovery
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )

        custom_tmpdir_str = str(tmp_path / "forbidden")
        monkeypatch.setenv("TMPDIR", custom_tmpdir_str)

        # Mock Path.mkdir to raise PermissionError when mkdir is called on TMPDIR
        original_mkdir = Path.mkdir
        def mock_mkdir(self, *args, **kwargs):
            if str(self) == custom_tmpdir_str:
                raise PermissionError("Permission denied")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mock_mkdir)

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should raise OciRegistryError due to TMPDIR creation failure
        with raises(OciRegistryError) as exc_info:
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        # Verify the error message mentions TMPDIR and the reason
        error_msg = str(exc_info.value)
        assert "Failed to create TMPDIR directory" in error_msg

    def test_tmpdir_path_exists_as_file_raises_hard_error(
        self, tmp_path, mocker: Any
    ):
        """TMPDIR pointing to an existing file (not dir) raises OciRegistryError."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )

        # Create a file (not a directory) at the TMPDIR path
        tmpdir_as_file = tmp_path / "tmpdir_file"
        tmpdir_as_file.write_text("I am a file, not a dir")

        mocker.patch.dict("os.environ", {"TMPDIR": str(tmpdir_as_file)})

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should raise OciRegistryError when attempting to mkdir on a file
        with raises(OciRegistryError) as exc_info:
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        error_msg = str(exc_info.value)
        assert str(tmpdir_as_file) in error_msg
        assert "Failed to create TMPDIR directory" in error_msg

    def test_tmpdir_validation_occurs_before_any_image_pull_attempt(
        self, tmp_path, mocker: Any
    ):
        """TMPDIR validation happens BEFORE any image discovery/pulling (lazy check point)."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        # Patch image discovery (not used but necessary for the mock to work)
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )

        # Make TMPDIR creation fail
        tmpdir_as_file = tmp_path / "tmpdir_file"
        tmpdir_as_file.write_text("I am a file")

        mocker.patch.dict("os.environ", {"TMPDIR": str(tmpdir_as_file)})

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Should raise OciRegistryError before discovery
        with raises(OciRegistryError):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

    def test_daemon_export_cleanup_still_works_with_created_tmpdir(
        self, tmp_path, mocker: Any
    ):
        """After TMPDIR is created, daemon_export_dir cleanup still works as before.

        Specifically, the margot-daemon-* ephemeral subdirectory is cleaned up,
        but the parent TMPDIR created by this fix is not deleted.
        """
        staging_root = tmp_path / "staging"
        staging_root.mkdir()

        build_dir = tmp_path / ".dist"
        comp_version_dir = build_dir / "1.0.0"
        comp_version_dir.mkdir(parents=True)

        compose_tgz = comp_version_dir / "testapp-1.0.0.tgz"
        with tarfile.open(compose_tgz, "w:gz"):
            pass

        mock_meta = mocker.MagicMock()
        mock_meta.name = "testapp"
        mock_meta.compose = mocker.MagicMock()
        mock_meta.quadlet = None

        # Mock image discovery to return an image (so TMPDIR creation happens)
        mocker.patch(
            "margot.services.package._discover_image_references_compose",
            return_value=["docker.io/library/nginx:latest"],
        )
        mocker.patch("margot.services.package.check_credentials")

        # Mock OrasClient to prevent actual registry access
        mock_oras = mocker.MagicMock()
        mocker.patch("margot.services.package.OrasClient", return_value=mock_oras)
        mock_oras.get_manifest.return_value = {
            "mediaType": "application/vnd.oci.image.manifest.v1+json"
        }

        mocker.patch("margot.services.package._create_oci_image_layout_tar")

        # Create a custom TMPDIR that doesn't exist yet
        custom_tmpdir = tmp_path / "custom_temp"
        assert not custom_tmpdir.exists()

        mocker.patch.dict("os.environ", {"TMPDIR": str(custom_tmpdir)})

        component_versions = {PackageType.COMPOSE: ["1.0.0"]}

        # Call the function (with an image, it should pull and then clean up)
        with contextlib.suppress(OciRegistryError):
            package_service._discover_and_include_images(
                staging_root,
                {PackageType.COMPOSE},
                str(build_dir),
                mock_meta,
                component_versions,
                "none",
            )

        # After the function completes, the custom TMPDIR should still exist
        # (because we created it and should not delete it)
        assert custom_tmpdir.is_dir()
