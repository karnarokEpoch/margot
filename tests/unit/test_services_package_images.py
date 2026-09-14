"""Unit tests for services/package.py image discovery and inclusion."""

import contextlib
from json import JSONDecodeError
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
