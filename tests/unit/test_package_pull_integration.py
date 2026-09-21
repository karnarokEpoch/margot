"""Unit tests for image pulling and inclusion in package service - integrated tests."""

import hashlib
import json
from pathlib import Path
import tarfile
from unittest.mock import MagicMock

from pytest import raises

from margot.infra.oci import OciRegistryError
from margot.services import package as package_service


class TestBlobVerification:
    """Tests for blob digest verification."""

    def test_blob_digest_verification_success(self, tmp_path):
        """Blob digest verification should pass for correct content."""
        blob_content = b"test blob content"
        blob_path = tmp_path / "test_blob"
        blob_path.write_bytes(blob_content)

        actual_digest = "sha256:" + hashlib.sha256(blob_content).hexdigest()
        # Should not raise
        package_service._verify_blob_digest(blob_path, actual_digest)

    def test_blob_digest_verification_failure(self, tmp_path):
        """Blob digest verification should fail for mismatched content."""
        blob_content = b"test blob content"
        blob_path = tmp_path / "test_blob"
        blob_path.write_bytes(blob_content)

        wrong_digest = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

        with raises(OciRegistryError, match="Blob digest mismatch"):
            package_service._verify_blob_digest(blob_path, wrong_digest)


class TestOCILayoutCreationWithRealBlobs:
    """Tests for OCI image layout tar creation with real blob content."""

    def test_creates_valid_oci_layout_single_platform(self, tmp_path):
        """Should create valid OCI layout tar for single-platform manifest."""
        # Create real blob content and compute digests
        config_content = b'{"architecture":"amd64","os":"linux"}'
        config_digest = "sha256:" + hashlib.sha256(config_content).hexdigest()

        layer_content = b"fake layer tar.gz content here"
        layer_digest = "sha256:" + hashlib.sha256(layer_content).hexdigest()

        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": config_digest,
                "size": len(config_content),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": layer_digest,
                    "size": len(layer_content),
                }
            ],
        }

        def mock_download(_container, digest, outfile):
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            if digest == config_digest:
                Path(outfile).write_bytes(config_content)
            elif digest == layer_digest:
                Path(outfile).write_bytes(layer_content)

        mock_client = MagicMock()
        mock_client.download_blob.side_effect = mock_download

        output_tar = tmp_path / "image.tar"
        package_service._create_oci_image_layout_tar(
            "nginx:latest",
            manifest,
            mock_client,
            str(output_tar),
        )

        # Verify tar was created
        assert output_tar.exists()

        # Verify tar contains expected structure
        with tarfile.open(output_tar, "r") as tar:
            members = [m.name for m in tar.getmembers()]
            assert any("oci-layout" in m for m in members)
            assert any("index.json" in m for m in members)
            assert any(config_digest.split(":")[1] in m for m in members)
            assert any(layer_digest.split(":")[1] in m for m in members)

            # Verify oci-layout is valid
            oci_layout_member = next((m for m in tar.getmembers() if "oci-layout" in m.name), None)
            assert oci_layout_member is not None
            oci_file = tar.extractfile(oci_layout_member)
            oci_data = json.load(oci_file)
            assert oci_data.get("imageLayoutVersion") == "1.0.0"

    def test_creates_valid_oci_layout_multi_platform(self, tmp_path):
        """Should create valid OCI layout for multi-platform index."""
        # Create blobs for two platforms
        amd64_config = b'{"architecture":"amd64"}'
        amd64_config_digest = "sha256:" + hashlib.sha256(amd64_config).hexdigest()

        arm64_config = b'{"architecture":"arm64"}'
        arm64_config_digest = "sha256:" + hashlib.sha256(arm64_config).hexdigest()

        amd64_layer = b"amd64 layer content"
        amd64_layer_digest = "sha256:" + hashlib.sha256(amd64_layer).hexdigest()

        arm64_layer = b"arm64 layer content"
        arm64_layer_digest = "sha256:" + hashlib.sha256(arm64_layer).hexdigest()

        # Create child manifests
        amd64_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "digest": amd64_config_digest,
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": len(amd64_config),
            },
            "layers": [
                {
                    "digest": amd64_layer_digest,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": len(amd64_layer),
                }
            ],
        }

        arm64_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "digest": arm64_config_digest,
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": len(arm64_config),
            },
            "layers": [
                {
                    "digest": arm64_layer_digest,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": len(arm64_layer),
                }
            ],
        }

        # Compute digests for child manifests
        amd64_manifest_json = json.dumps(amd64_manifest, separators=(",", ":"), sort_keys=True)
        amd64_manifest_digest = "sha256:" + hashlib.sha256(amd64_manifest_json.encode()).hexdigest()

        arm64_manifest_json = json.dumps(arm64_manifest, separators=(",", ":"), sort_keys=True)
        arm64_manifest_digest = "sha256:" + hashlib.sha256(arm64_manifest_json.encode()).hexdigest()

        # Create index
        index = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": amd64_manifest_digest,
                    "size": len(amd64_manifest_json),
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": arm64_manifest_digest,
                    "size": len(arm64_manifest_json),
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
            ],
        }

        def mock_download(_container, digest, outfile):
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            if digest == amd64_manifest_digest:
                Path(outfile).write_text(amd64_manifest_json)
            elif digest == arm64_manifest_digest:
                Path(outfile).write_text(arm64_manifest_json)
            elif digest == amd64_config_digest:
                Path(outfile).write_bytes(amd64_config)
            elif digest == arm64_config_digest:
                Path(outfile).write_bytes(arm64_config)
            elif digest == amd64_layer_digest:
                Path(outfile).write_bytes(amd64_layer)
            elif digest == arm64_layer_digest:
                Path(outfile).write_bytes(arm64_layer)

        mock_client = MagicMock()
        mock_client.download_blob.side_effect = mock_download

        output_tar = tmp_path / "multi-arch.tar"
        package_service._create_oci_image_layout_tar(
            "nginx:latest",
            index,
            mock_client,
            str(output_tar),
        )

        # Verify tar was created and contains all blobs
        assert output_tar.exists()

        with tarfile.open(output_tar, "r") as tar:
            members = [m.name for m in tar.getmembers()]
            # Verify both platforms' blobs are present
            assert any(amd64_config_digest.split(":")[1] in m for m in members)
            assert any(arm64_config_digest.split(":")[1] in m for m in members)
            assert any(amd64_layer_digest.split(":")[1] in m for m in members)
            assert any(arm64_layer_digest.split(":")[1] in m for m in members)


class TestManifestDigestComputation:
    """Tests for manifest digest computation."""

    def test_manifest_digest_computation(self):
        """Manifest digest should be consistent."""
        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "digest": "sha256:abc123",
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": 100,
            },
            "layers": [],
        }

        digest1 = package_service._compute_manifest_digest(manifest)
        digest2 = package_service._compute_manifest_digest(manifest)

        assert digest1 == digest2
        assert digest1.startswith("sha256:")
        assert len(digest1) == 71  # sha256: (7) + 64 hex chars


class TestDownloadManifestBlobs:
    """Tests for downloading manifest blobs."""

    def test_downloads_config_and_layers(self, tmp_path):
        """Should download all blobs referenced in manifest."""
        config_content = b'{"config":"data"}'
        config_digest = "sha256:" + hashlib.sha256(config_content).hexdigest()

        layer1_content = b"layer 1 content"
        layer1_digest = "sha256:" + hashlib.sha256(layer1_content).hexdigest()

        layer2_content = b"layer 2 content"
        layer2_digest = "sha256:" + hashlib.sha256(layer2_content).hexdigest()

        manifest = {
            "config": {
                "digest": config_digest,
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": len(config_content),
            },
            "layers": [
                {
                    "digest": layer1_digest,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": len(layer1_content),
                },
                {
                    "digest": layer2_digest,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": len(layer2_content),
                },
            ],
        }

        download_calls = []

        def mock_download(_container, digest, outfile):
            download_calls.append((digest, outfile))
            Path(outfile).parent.mkdir(parents=True, exist_ok=True)
            if digest == config_digest:
                Path(outfile).write_bytes(config_content)
            elif digest == layer1_digest:
                Path(outfile).write_bytes(layer1_content)
            elif digest == layer2_digest:
                Path(outfile).write_bytes(layer2_content)

        mock_client = MagicMock()
        mock_client.download_blob.side_effect = mock_download

        blobs_dir = tmp_path / "blobs" / "sha256"
        blobs_dir.mkdir(parents=True)

        package_service._download_manifest_blobs(
            manifest,
            mock_client,
            "nginx:latest",
            blobs_dir,
        )

        # All three blobs should have been downloaded
        assert len(download_calls) == 3
        assert all(call[0] in [config_digest, layer1_digest, layer2_digest] for call in download_calls)

        # All blob files should exist
        config_file = blobs_dir / config_digest.split(":")[1]
        assert config_file.exists()
        assert config_file.read_bytes() == config_content

        layer1_file = blobs_dir / layer1_digest.split(":")[1]
        assert layer1_file.exists()
        assert layer1_file.read_bytes() == layer1_content

        layer2_file = blobs_dir / layer2_digest.split(":")[1]
        assert layer2_file.exists()
        assert layer2_file.read_bytes() == layer2_content
