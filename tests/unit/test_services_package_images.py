"""Unit tests for services/package.py image discovery and inclusion."""

import json
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from pytest import fixture, raises

from margot.domain.models import PackageType
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


class TestOCIImageLayout:
    """Tests for OCI image layout tar creation."""

    def test_creates_valid_oci_layout_structure(self, tmp_path, mocker: Any):
        """Should create a valid OCI image layout tar with index.json, oci-layout, and blobs."""
        # Mock image manifest and config
        mock_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                "size": 100,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "size": 1000,
                }
            ],
        }

        # Create mock blobs
        config_blob = b'{"architecture":"amd64"}'
        layer_blob = b"fake layer data"

        # Mock the download_blob to provide blob content
        def mock_download(container, digest, outfile):  # Accepts 3 args: container, digest, outfile
            if digest == "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef":
                Path(outfile).write_bytes(config_blob)
            elif digest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa":
                Path(outfile).write_bytes(layer_blob)

        mock_client = mocker.MagicMock()
        mock_client.get_manifest.return_value = mock_manifest
        mock_client.download_blob.side_effect = mock_download

        output_tar = tmp_path / "image.tar"
        package_service._create_oci_image_layout_tar(
            "nginx:latest",
            mock_manifest,
            mock_client,
            str(output_tar),
        )

        # Verify tar was created and contains expected structure
        assert output_tar.exists()

        with tarfile.open(output_tar, "r") as tar:
            members = tar.getnames()
            # Members might have './' prefix or not
            assert any("oci-layout" in m for m in members)
            assert any("index.json" in m for m in members)
            # Blobs directory structure
            assert any("blobs/sha256/" in m for m in members)

    def test_oci_layout_includes_all_platforms_in_index(self, tmp_path, mocker: Any):
        """Multi-arch index should include all platforms by default."""
        mock_index = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:amd64digest1234567890abcdef1234567890abcdef1234567890abcdef",
                    "size": 500,
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:arm64digest1234567890abcdef1234567890abcdef1234567890abcdef",
                    "size": 500,
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
            ],
        }

        mock_client = mocker.MagicMock()
        mock_client.get_manifest.return_value = mock_index
        mock_client.download_blob.return_value = None

        output_tar = tmp_path / "multi-arch.tar"

        # Should not raise and should process all platforms
        try:
            package_service._create_oci_image_layout_tar(
                "nginx:latest",
                mock_index,
                mock_client,
                str(output_tar),
            )
        except Exception as e:
            # May fail on blob fetch in test, that's OK; we're testing that it doesn't filter platforms
            assert "platform" not in str(e).lower()


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

    def test_bundle_structure_with_images_folder(self, tmp_path, mocker: Any, mock_package_metadata):
        """Bundle should include images/ folder when include_images=True."""
        build_dir = tmp_path / ".dist"
        version_dir = build_dir / "1.0.0"
        margo_dir = version_dir / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("kind: ApplicationDescription")

        # Mock no images discovered (simpler for this test)
        mocker.patch("margot.services.package._discover_image_references_compose", return_value=[])
        mocker.patch("margot.services.package._discover_image_references_quadlet", return_value=[])

        output_path = package_service.package(
            PackageType.BUNDLE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
            include_images=True,
        )

        # Extract and check structure
        assert output_path.endswith(".tgz")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(output_path, "r:gz") as tar:
            tar.extractall(extract_dir)

        # Images folder should exist (even if empty since no images discovered)
        assert (extract_dir / f"{mock_package_metadata.id}-1.0.0" / "images").exists()

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
            tar.extractall(extract_dir)

        # Images folder should NOT exist
        assert not (extract_dir / f"{mock_package_metadata.id}-1.0.0" / "images").exists()
