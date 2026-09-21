"""Tests for Docker tarball to OCI layout normalization."""

from hashlib import sha256
from json import dumps as json_dumps
from json import load as json_load
from pathlib import Path
from tarfile import open as tar_open
from typing import Any

from pytest import fixture, raises

from margot.infra.oci import OrasClient
from margot.services import package as package_service


@fixture
def docker_tarball_fixture(tmp_path: Path) -> tuple[str, dict[str, Any]]:
    """Create a minimal but realistic Docker tarball fixture.

    Returns a tuple of (tarball_path, metadata_dict) where metadata includes
    config and layer digests for assertion.
    """
    docker_tar_dir = tmp_path / "docker_archive"
    docker_tar_dir.mkdir()

    # Create a minimal config blob
    config_data = {
        "architecture": "amd64",
        "os": "linux",
        "mediaType": "application/vnd.docker.container.image.v1+json",
        "config": {"Hostname": "test"},
        "rootfs": {"type": "layers", "diff_ids": []},
    }
    config_json = json_dumps(config_data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    config_digest = f"sha256:{sha256(config_json).hexdigest()}"
    config_filename = config_digest.rsplit(":", maxsplit=1)[-1] + ".json"

    # Create a minimal layer (just a small tar.gz)
    layer_tar_path = docker_tar_dir / "layer_0" / "layer.tar.gz"
    layer_tar_path.parent.mkdir(parents=True)
    # Create a minimal gzip file (this is technically invalid tar.gz but sufficient for testing)
    layer_tar_path.write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    layer_digest = f"sha256:{sha256(layer_tar_path.read_bytes()).hexdigest()}"
    layer_filename = "layer_0/layer.tar.gz"

    # Create manifest.json (Docker's format)
    manifest_entry = {
        "Config": config_filename,
        "Layers": [layer_filename],
        "RepoTags": ["test:latest"],
    }
    manifest_data = [manifest_entry]

    # Write config file to Docker archive
    config_path = docker_tar_dir / config_filename
    config_path.write_bytes(config_json)

    # Write manifest.json
    manifest_path = docker_tar_dir / "manifest.json"
    manifest_path.write_text(json_dumps(manifest_data))

    # Create the Docker tarball
    docker_tar_path = tmp_path / "test.docker.tar"
    with tar_open(docker_tar_path, "w") as tar:
        tar.add(docker_tar_dir, arcname=".", recursive=True)

    metadata = {
        "config_digest": config_digest,
        "config_filename": config_filename,
        "layer_digest": layer_digest,
        "layer_filename": layer_filename,
    }

    return str(docker_tar_path), metadata


class TestNormalizeDockerTarballToOciLayout:
    """Tests for _normalize_docker_tarball_to_oci_layout()."""

    def test_normalizes_docker_tarball_to_oci_layout(
        self,
        docker_tarball_fixture: tuple[str, dict[str, Any]],
        tmp_path: Path,
    ) -> None:
        """Should convert Docker tarball to valid OCI image layout tar."""
        docker_tar_path, _metadata = docker_tarball_fixture

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Call the normalization function
        oras_client = OrasClient()
        result = package_service._normalize_docker_tarball_to_oci_layout(
            docker_tar_path,
            "docker.io/library/test:latest",
            str(output_dir),
            oras_client,
        )

        # Verify result path exists and is a valid tar file
        assert result is not None
        assert Path(result).exists()

        # Extract and verify OCI layout structure
        temp_extract = tmp_path / "extracted"
        temp_extract.mkdir()

        with tar_open(result, "r") as tar:
            tar.extractall(temp_extract, filter="data")

        # Verify oci-layout file exists and is valid JSON
        oci_layout_file = temp_extract / "oci-layout"
        assert oci_layout_file.exists()
        oci_layout = json_load(oci_layout_file.open())
        assert oci_layout["imageLayoutVersion"] == "1.0.0"

        # Verify index.json exists and is valid
        index_json_file = temp_extract / "index.json"
        assert index_json_file.exists()
        index = json_load(index_json_file.open())
        assert index["schemaVersion"] == 2
        assert index["mediaType"] == "application/vnd.oci.image.index.v1+json"
        assert len(index["manifests"]) > 0

        # Verify manifest has ref-name annotation
        manifest_entry = index["manifests"][0]
        assert "annotations" in manifest_entry
        assert manifest_entry["annotations"]["org.opencontainers.image.ref.name"] == "docker.io/library/test:latest"

        # Verify blobs directory structure
        blobs_dir = temp_extract / "blobs" / "sha256"
        assert blobs_dir.exists()

        # Verify config blob exists
        manifest_digest = manifest_entry["digest"]
        manifest_blob_filename = manifest_digest.split(":")[-1]
        manifest_blob_path = blobs_dir / manifest_blob_filename
        assert manifest_blob_path.exists()

        # Verify manifest blob is valid JSON
        manifest_blob = json_load(manifest_blob_path.open())
        assert manifest_blob["schemaVersion"] == 2
        assert manifest_blob["mediaType"] == "application/vnd.oci.image.manifest.v1+json"

        # Verify all blobs in manifest are present
        config_digest = manifest_blob["config"]["digest"]
        config_blob_filename = config_digest.split(":")[-1]
        assert (blobs_dir / config_blob_filename).exists()

        for layer in manifest_blob["layers"]:
            layer_digest = layer["digest"]
            layer_blob_filename = layer_digest.split(":")[-1]
            assert (blobs_dir / layer_blob_filename).exists()

    def test_translates_docker_media_types_to_oci(
        self,
        docker_tarball_fixture: tuple[str, dict[str, Any]],
        tmp_path: Path,
    ) -> None:
        """Should translate Docker legacy media types to OCI equivalents."""
        docker_tar_path, _metadata = docker_tarball_fixture

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        oras_client = OrasClient()
        result = package_service._normalize_docker_tarball_to_oci_layout(
            docker_tar_path,
            "docker.io/library/test:latest",
            str(output_dir),
            oras_client,
        )

        # Extract and verify media types
        temp_extract = tmp_path / "extracted"
        temp_extract.mkdir()

        with tar_open(result, "r") as tar:
            tar.extractall(temp_extract, filter="data")

        index = json_load((temp_extract / "index.json").open())
        manifest_entry = index["manifests"][0]
        manifest_digest = manifest_entry["digest"]
        manifest_blob_filename = manifest_digest.split(":")[-1]
        manifest_blob = json_load((temp_extract / "blobs" / "sha256" / manifest_blob_filename).open())

        # Config media type should be OCI, not Docker legacy
        config_media_type = manifest_blob["config"]["mediaType"]
        assert config_media_type == "application/vnd.oci.image.config.v1+json"

        # Layer media types should be OCI
        for layer in manifest_blob["layers"]:
            layer_media_type = layer["mediaType"]
            assert "vnd.oci.image.layer" in layer_media_type
            assert "vnd.docker" not in layer_media_type

    def test_computes_real_sha256_digests(
        self,
        docker_tarball_fixture: tuple[str, dict[str, Any]],
        tmp_path: Path,
    ) -> None:
        """Should compute real sha256 digests for all blobs."""
        docker_tar_path, _metadata = docker_tarball_fixture

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        oras_client = OrasClient()
        result = package_service._normalize_docker_tarball_to_oci_layout(
            docker_tar_path,
            "docker.io/library/test:latest",
            str(output_dir),
            oras_client,
        )

        # Extract and verify digests match actual blob content
        temp_extract = tmp_path / "extracted"
        temp_extract.mkdir()

        with tar_open(result, "r") as tar:
            tar.extractall(temp_extract, filter="data")

        index = json_load((temp_extract / "index.json").open())
        manifest_entry = index["manifests"][0]
        manifest_digest = manifest_entry["digest"]
        manifest_blob_filename = manifest_digest.split(":")[-1]
        manifest_blob_path = temp_extract / "blobs" / "sha256" / manifest_blob_filename

        # Verify manifest digest is correct
        manifest_content = manifest_blob_path.read_bytes()
        computed_manifest_digest = f"sha256:{sha256(manifest_content).hexdigest()}"
        assert computed_manifest_digest == manifest_digest

        # Read manifest to get config and layer digests
        manifest_blob = json_load(manifest_blob_path.open())

        # Verify config digest
        config_digest = manifest_blob["config"]["digest"]
        config_filename = config_digest.split(":")[-1]
        config_blob_path = temp_extract / "blobs" / "sha256" / config_filename
        config_content = config_blob_path.read_bytes()
        computed_config_digest = f"sha256:{sha256(config_content).hexdigest()}"
        assert computed_config_digest == config_digest

        # Verify layer digests
        for layer in manifest_blob["layers"]:
            layer_digest = layer["digest"]
            layer_filename = layer_digest.split(":")[-1]
            layer_blob_path = temp_extract / "blobs" / "sha256" / layer_filename
            layer_content = layer_blob_path.read_bytes()
            computed_layer_digest = f"sha256:{sha256(layer_content).hexdigest()}"
            assert computed_layer_digest == layer_digest

    def test_missing_manifest_json_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError if manifest.json is missing."""
        # Create a Docker tarball without manifest.json
        docker_tar_dir = tmp_path / "docker_archive"
        docker_tar_dir.mkdir()

        config_data = {"architecture": "amd64", "os": "linux"}
        config_filename = "config.json"
        config_path = docker_tar_dir / config_filename
        config_path.write_text(json_dumps(config_data))

        docker_tar_path = tmp_path / "test.docker.tar"
        with tar_open(docker_tar_path, "w") as tar:
            tar.add(docker_tar_dir, arcname=".", recursive=True)

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        oras_client = OrasClient()

        with raises(ValueError, match=r"manifest\.json"):
            package_service._normalize_docker_tarball_to_oci_layout(
                str(docker_tar_path),
                "docker.io/library/test:latest",
                str(output_dir),
                oras_client,
            )

    def test_invalid_manifest_json_format_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError if manifest.json is not a list."""
        docker_tar_dir = tmp_path / "docker_archive"
        docker_tar_dir.mkdir()

        # Write invalid manifest.json (dict instead of list)
        manifest_path = docker_tar_dir / "manifest.json"
        manifest_path.write_text(json_dumps({"invalid": "format"}))

        docker_tar_path = tmp_path / "test.docker.tar"
        with tar_open(docker_tar_path, "w") as tar:
            tar.add(docker_tar_dir, arcname=".", recursive=True)

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        oras_client = OrasClient()

        with raises(ValueError, match=r"non-empty list"):
            package_service._normalize_docker_tarball_to_oci_layout(
                str(docker_tar_path),
                "docker.io/library/test:latest",
                str(output_dir),
                oras_client,
            )

    def test_missing_config_blob_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError if config blob is missing."""
        docker_tar_dir = tmp_path / "docker_archive"
        docker_tar_dir.mkdir()

        # Create manifest that references a config file that doesn't exist
        manifest_entry = {
            "Config": "nonexistent_config.json",
            "Layers": [],
        }
        manifest_path = docker_tar_dir / "manifest.json"
        manifest_path.write_text(json_dumps([manifest_entry]))

        docker_tar_path = tmp_path / "test.docker.tar"
        with tar_open(docker_tar_path, "w") as tar:
            tar.add(docker_tar_dir, arcname=".", recursive=True)

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        oras_client = OrasClient()

        with raises(ValueError, match=r"config blob"):
            package_service._normalize_docker_tarball_to_oci_layout(
                str(docker_tar_path),
                "docker.io/library/test:latest",
                str(output_dir),
                oras_client,
            )

    def test_missing_layer_blob_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError if a layer blob is missing."""
        docker_tar_dir = tmp_path / "docker_archive"
        docker_tar_dir.mkdir()

        # Create config blob
        config_data = {"architecture": "amd64"}
        config_filename = "config.json"
        config_path = docker_tar_dir / config_filename
        config_path.write_text(json_dumps(config_data))

        # Create manifest that references a layer that doesn't exist
        manifest_entry = {
            "Config": config_filename,
            "Layers": ["nonexistent_layer.tar.gz"],
        }
        manifest_path = docker_tar_dir / "manifest.json"
        manifest_path.write_text(json_dumps([manifest_entry]))

        docker_tar_path = tmp_path / "test.docker.tar"
        with tar_open(docker_tar_path, "w") as tar:
            tar.add(docker_tar_dir, arcname=".", recursive=True)

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        oras_client = OrasClient()

        with raises(ValueError, match=r"layer blob"):
            package_service._normalize_docker_tarball_to_oci_layout(
                str(docker_tar_path),
                "docker.io/library/test:latest",
                str(output_dir),
                oras_client,
            )

    def test_output_filename_based_on_image_ref(
        self,
        docker_tarball_fixture: tuple[str, dict[str, Any]],
        tmp_path: Path,
    ) -> None:
        """Output filename should be derived from image reference."""
        docker_tar_path, _metadata = docker_tarball_fixture

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        image_ref = "docker.io/library/myapp:v1.2.3"

        oras_client = OrasClient()
        result = package_service._normalize_docker_tarball_to_oci_layout(
            docker_tar_path,
            image_ref,
            str(output_dir),
            oras_client,
        )

        # Verify filename is based on image ref with safe substitutions
        result_path = Path(result)
        expected_filename_prefix = image_ref.replace("/", "_").replace(":", "_")
        assert expected_filename_prefix in result_path.name

    def test_layer_media_type_detection(
        self,
        docker_tarball_fixture: tuple[str, dict[str, Any]],
        tmp_path: Path,
    ) -> None:
        """Should detect and set appropriate media types for layers."""
        docker_tar_path, _metadata = docker_tarball_fixture

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        oras_client = OrasClient()
        result = package_service._normalize_docker_tarball_to_oci_layout(
            docker_tar_path,
            "test:latest",
            str(output_dir),
            oras_client,
        )

        temp_extract = tmp_path / "extracted"
        temp_extract.mkdir()

        with tar_open(result, "r") as tar:
            tar.extractall(temp_extract, filter="data")

        index = json_load((temp_extract / "index.json").open())
        manifest_entry = index["manifests"][0]
        manifest_digest = manifest_entry["digest"]
        manifest_blob_filename = manifest_digest.split(":")[-1]
        manifest_blob = json_load((temp_extract / "blobs" / "sha256" / manifest_blob_filename).open())

        # Verify layer media type is set based on filename extension
        for layer in manifest_blob["layers"]:
            assert layer["mediaType"] in [
                "application/vnd.oci.image.layer.v1.tar+gzip",
                "application/vnd.oci.image.layer.v1.tar",
            ]
