"""Unit tests for manifest list fallback in Podman image lookup."""

import contextlib
import gzip
from hashlib import sha256 as sha256_hash
from io import BytesIO
from json import dumps as json_dumps
from json import loads as json_loads
from pathlib import Path
import subprocess
from tarfile import TarInfo
from tarfile import open as tar_open
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, Mock, patch

from pytest import mark, raises, skip

try:
    from podman import PodmanClient
except ImportError:
    PodmanClient = None  # type: ignore[assignment]

from margot import console
from margot.services import package as package_service


class TestGetHostPlatform:
    """Tests for _get_host_platform helper."""

    def test_returns_valid_platform_string(self):
        """Should return a valid os/arch format platform string."""
        platform = package_service._get_host_platform()
        assert isinstance(platform, str)
        parts = platform.split("/")
        assert len(parts) == 2
        assert parts[0]  # os is non-empty
        assert parts[1]  # arch is non-empty

    @patch("margot.services.package.platform_module.system")
    @patch("margot.services.package.platform_module.machine")
    def test_normalizes_x86_64_to_amd64(self, mock_machine, mock_system):
        """Should normalize x86_64 machine to amd64."""
        mock_system.return_value = "Linux"
        mock_machine.return_value = "x86_64"
        assert package_service._get_host_platform() == "linux/amd64"

    @patch("margot.services.package.platform_module.system")
    @patch("margot.services.package.platform_module.machine")
    def test_normalizes_aarch64_to_arm64(self, mock_machine, mock_system):
        """Should normalize aarch64 machine to arm64."""
        mock_system.return_value = "Linux"
        mock_machine.return_value = "aarch64"
        assert package_service._get_host_platform() == "linux/arm64"

    @patch("margot.services.package.platform_module.system")
    @patch("margot.services.package.platform_module.machine")
    def test_normalizes_armv7l_to_arm(self, mock_machine, mock_system):
        """Should normalize armv7l machine to arm."""
        mock_system.return_value = "Linux"
        mock_machine.return_value = "armv7l"
        assert package_service._get_host_platform() == "linux/arm"

    @patch("margot.services.package.platform_module.system")
    @patch("margot.services.package.platform_module.machine")
    def test_preserves_unknown_arch(self, mock_machine, mock_system):
        """Should preserve unknown architectures as-is."""
        mock_system.return_value = "Linux"
        mock_machine.return_value = "unknown_arch"
        assert package_service._get_host_platform() == "linux/unknown_arch"

    @patch("margot.services.package.platform_module.system")
    @patch("margot.services.package.platform_module.machine")
    def test_lowercases_system_name(self, mock_machine, mock_system):
        """Should lowercase the system name."""
        mock_system.return_value = "Darwin"
        mock_machine.return_value = "arm64"
        assert package_service._get_host_platform() == "darwin/arm64"


class TestExportImageToOciArchive:
    """Tests for _export_image_to_oci_archive helper."""

    def test_exports_image_successfully(self):
        """Should export image to OCI archive format via client.get()."""
        with TemporaryDirectory() as tmpdir:
            # Create a mock image with the attributes the real Image class has:
            # id, client (APIClient), and attrs
            mock_image = Mock(spec=["id", "client", "attrs"])
            mock_image.id = "sha256:abc123def456"
            mock_image.attrs = {}

            # Mock the HTTP client response
            mock_response = Mock()
            mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
            mock_image.client.get.return_value = mock_response

            result = package_service._export_image_to_oci_archive(
                mock_image, "test/image:1.0", tmpdir
            )

            assert result is not None
            assert result.endswith(".tar")
            assert Path(result).exists()
            assert Path(result).read_bytes() == b"chunk1chunk2"

            # Verify the client.get() was called with the correct endpoint and params
            mock_image.client.get.assert_called_once_with(
                "/images/sha256:abc123def456/get",
                params={"format": ["oci-archive"]},
                stream=True,
            )

    def test_handles_export_failure(self):
        """Should return None if export fails."""
        with TemporaryDirectory() as tmpdir:
            mock_image = Mock(spec=["id", "client", "attrs"])
            mock_image.id = "sha256:abc123def456"
            mock_image.client.get.side_effect = RuntimeError("Export failed")

            result = package_service._export_image_to_oci_archive(
                mock_image, "test/image:1.0", tmpdir
            )

            assert result is None

    def test_generates_safe_filename(self):
        """Should generate safe filenames from image references."""
        with TemporaryDirectory() as tmpdir:
            mock_image = Mock(spec=["id", "client", "attrs"])
            mock_image.id = "sha256:abc123def456"

            mock_response = Mock()
            mock_response.iter_content.return_value = [b"data"]
            mock_image.client.get.return_value = mock_response

            result = package_service._export_image_to_oci_archive(
                mock_image, "public.ecr.aws/org/app:1.0.0", tmpdir
            )

            filename = Path(result).name
            # Slashes and colons should be replaced with underscores
            assert "/" not in filename
            assert ":" not in filename
            assert filename.endswith(".tar")


class TestLookupImagePodmanDirectHit:
    """Tests for _lookup_image_podman with direct image hits."""

    @patch("margot.services.package._export_image_to_oci_archive")
    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_direct_hit_success(self, mock_podman_client_cls, mock_socket_uri, mock_export):
        """Should return exported path on direct image hit."""
        mock_socket_uri.return_value = "unix:///run/user/1000/podman/podman.sock"
        mock_export.return_value = "/tmp/image.tar"

        mock_client = MagicMock()
        mock_image = Mock()
        mock_client.images.get.return_value = mock_image
        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        result = package_service._lookup_image_podman("nginx:latest", "/tmp")

        assert result == "/tmp/image.tar"
        mock_client.images.get.assert_called_once_with("nginx:latest")
        mock_export.assert_called_once()

    @patch("margot.services.package.PodmanClient")
    def test_direct_hit_not_found_no_manifest(self, mock_podman_client_cls):
        """Should return None when image not found and manifest doesn't exist."""
        mock_client = MagicMock()
        mock_client.images.get.side_effect = RuntimeError("Not found")
        mock_client.manifests.exists.return_value = False
        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        result = package_service._lookup_image_podman("nonexistent:latest", "/tmp")

        assert result is None
        mock_client.manifests.exists.assert_called_once_with("nonexistent:latest")


class TestLookupImagePodmanManifestListFallback:
    """Tests for _lookup_image_podman with manifest list fallback."""

    @patch("margot.services.package._get_host_platform")
    @patch("margot.services.package._export_image_to_oci_archive")
    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_manifest_list_single_platform_match(
        self, mock_podman_client_cls, mock_socket_uri, mock_export, mock_get_platform
    ):
        """Should resolve image via manifest list with single matching platform."""
        mock_socket_uri.return_value = "unix:///run/user/1000/podman/podman.sock"
        mock_get_platform.return_value = "linux/amd64"
        mock_export.return_value = "/tmp/image.tar"

        # Setup mock client
        mock_client = MagicMock()

        # Direct image lookup fails
        mock_client.images.get.side_effect = RuntimeError("Not found")

        # Manifest list exists and has one matching entry
        mock_manifest = Mock()
        mock_manifest.attrs = {
            "manifests": [
                {
                    "digest": "sha256:abc123",
                    "platform": {"os": "linux", "architecture": "amd64"},
                }
            ]
        }
        mock_client.manifests.exists.return_value = True
        mock_client.manifests.get.return_value = mock_manifest

        # images.list() returns the concrete image for the digest
        mock_concrete_image = Mock()
        mock_client.images.list.return_value = [mock_concrete_image]

        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        result = package_service._lookup_image_podman("nginx:latest", "/tmp")

        assert result == "/tmp/image.tar"
        # Should have called images.get once (direct lookup)
        mock_client.images.get.assert_called_once_with("nginx:latest")
        # Should have called images.list with the digest
        mock_client.images.list.assert_called_once_with(filters={"digest": "sha256:abc123"})
        mock_client.manifests.exists.assert_called_once()
        mock_client.manifests.get.assert_called_once()

    @patch("margot.services.package._get_host_platform")
    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_manifest_list_multiple_platforms_selects_correct_one(
        self, mock_podman_client_cls, mock_socket_uri, mock_get_platform
    ):
        """Should select correct platform from multi-platform manifest list."""
        mock_socket_uri.return_value = "unix:///run/user/1000/podman/podman.sock"
        mock_get_platform.return_value = "linux/arm64"

        # Setup mock client
        mock_client = MagicMock()
        mock_client.images.get.side_effect = RuntimeError("Not found")

        # Manifest list with multiple entries
        mock_manifest = Mock()
        mock_manifest.attrs = {
            "manifests": [
                {
                    "digest": "sha256:amd64_digest",
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                {
                    "digest": "sha256:arm64_digest",
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
            ]
        }
        mock_client.manifests.exists.return_value = True
        mock_client.manifests.get.return_value = mock_manifest

        # images.list() returns the correct platform's image
        mock_concrete_image = Mock()
        mock_client.images.list.return_value = [mock_concrete_image]

        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        with patch("margot.services.package._export_image_to_oci_archive", return_value="/tmp/image.tar"):
            result = package_service._lookup_image_podman("nginx:latest", "/tmp")

        assert result == "/tmp/image.tar"
        # Should have called images.list with the arm64 digest (the matching platform)
        mock_client.images.list.assert_called_once_with(filters={"digest": "sha256:arm64_digest"})

    @patch("margot.services.package._get_host_platform")
    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_manifest_list_no_matching_platform(
        self, mock_podman_client_cls, mock_socket_uri, mock_get_platform
    ):
        """Should return None when no manifest entry matches host platform."""
        mock_socket_uri.return_value = "unix:///run/user/1000/podman/podman.sock"
        mock_get_platform.return_value = "linux/ppc64le"

        mock_client = MagicMock()
        mock_client.images.get.side_effect = RuntimeError("Not found")

        # Manifest list with no matching platform
        mock_manifest = Mock()
        mock_manifest.attrs = {
            "manifests": [
                {
                    "digest": "sha256:amd64_digest",
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                {
                    "digest": "sha256:arm64_digest",
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
            ]
        }
        mock_client.manifests.exists.return_value = True
        mock_client.manifests.get.return_value = mock_manifest

        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        result = package_service._lookup_image_podman("nginx:latest", "/tmp")

        assert result is None

    @patch("margot.services.package._get_host_platform")
    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_manifest_list_digest_lookup_fails(
        self, mock_podman_client_cls, mock_socket_uri, mock_get_platform
    ):
        """Should return None when platform matches but digest lookup fails."""
        mock_socket_uri.return_value = "unix:///run/user/1000/podman/podman.sock"
        mock_get_platform.return_value = "linux/amd64"

        mock_client = MagicMock()
        mock_client.images.get.side_effect = RuntimeError("Not found")

        mock_manifest = Mock()
        mock_manifest.attrs = {
            "manifests": [
                {
                    "digest": "sha256:abc123",
                    "platform": {"os": "linux", "architecture": "amd64"},
                }
            ]
        }
        mock_client.manifests.exists.return_value = True
        mock_client.manifests.get.return_value = mock_manifest

        # images.list() also fails (no images match the digest)
        mock_client.images.list.return_value = []

        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        result = package_service._lookup_image_podman("nginx:latest", "/tmp")

        assert result is None

    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_manifest_list_empty_entries(
        self, mock_podman_client_cls, mock_socket_uri
    ):
        """Should return None when manifest list has no entries."""
        mock_socket_uri.return_value = "unix:///run/user/1000/podman/podman.sock"

        mock_client = MagicMock()
        mock_client.images.get.side_effect = RuntimeError("Not found")

        mock_manifest = Mock()
        mock_manifest.attrs = {"manifests": []}
        mock_client.manifests.exists.return_value = True
        mock_client.manifests.get.return_value = mock_manifest

        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        result = package_service._lookup_image_podman("nginx:latest", "/tmp")

        assert result is None

    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_manifest_lookup_exception_handled(
        self, mock_podman_client_cls, mock_socket_uri
    ):
        """Should return None when manifest lookup raises exception."""
        mock_socket_uri.return_value = "unix:///run/user/1000/podman/podman.sock"

        mock_client = MagicMock()
        mock_client.images.get.side_effect = RuntimeError("Not found")
        mock_client.manifests.exists.return_value = True
        mock_client.manifests.get.side_effect = RuntimeError("Manifest fetch failed")

        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        result = package_service._lookup_image_podman("nginx:latest", "/tmp")

        assert result is None


class TestLookupImagePodmanRequired:
    """Tests for _lookup_image_podman with required=True."""

    @patch("margot.services.package.PodmanClient", None)
    def test_required_true_sdk_missing(self):
        """Should raise RuntimeError when SDK missing and required=True."""
        with raises(RuntimeError, match="Podman SDK not available"):
            package_service._lookup_image_podman("nginx:latest", "/tmp", required=True)

    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_required_true_socket_unreachable(self, mock_podman_client_cls, mock_socket_uri):
        """Should raise RuntimeError when socket unreachable and required=True."""
        mock_socket_uri.return_value = "unix:///nonexistent"
        mock_podman_client_cls.return_value.__enter__.side_effect = RuntimeError("Socket unreachable")

        with raises(RuntimeError, match="Podman socket unreachable"):
            package_service._lookup_image_podman("nginx:latest", "/tmp", required=True)


class TestPlatformMatchesManifestReused:
    """Tests to verify _platform_matches_manifest is reused in manifest list fallback."""

    @patch("margot.services.package._get_host_platform")
    @patch("margot.services.package._export_image_to_oci_archive")
    @patch("margot.services.package._resolve_podman_socket_uri")
    @patch("margot.services.package.PodmanClient")
    def test_platform_comparison_uses_existing_helper(
        self, mock_podman_client_cls, mock_socket_uri, mock_export, mock_get_platform
    ):
        """Should use _platform_matches_manifest for platform comparison."""
        mock_socket_uri.return_value = "unix:///run/user/1000/podman/podman.sock"
        mock_get_platform.return_value = "linux/arm/v7"
        mock_export.return_value = "/tmp/image.tar"

        mock_client = MagicMock()
        mock_client.images.get.side_effect = [
            RuntimeError("Not found"),
            Mock(),  # Digest lookup
        ]

        # Entry with variant to test _platform_matches_manifest
        mock_manifest = Mock()
        mock_manifest.attrs = {
            "manifests": [
                {
                    "digest": "sha256:armv7",
                    "platform": {"os": "linux", "architecture": "arm", "variant": "v7"},
                }
            ]
        }
        mock_client.manifests.exists.return_value = True
        mock_client.manifests.get.return_value = mock_manifest

        mock_podman_client_cls.return_value.__enter__.return_value = mock_client

        result = package_service._lookup_image_podman("nginx:latest", "/tmp")

        # If _platform_matches_manifest is correctly used, should match
        assert result == "/tmp/image.tar"


class TestResolveAllPlatformsRealSocket:
    """Real socket tests for _resolve_all_platforms_from_manifest_list.

    These tests exercise the actual Podman SDK call paths against a real socket
    if available, ensuring that the images.list(filters={"digest": ...}) call
    works as expected and that manifest-list child digests are correctly resolved.
    """

    @staticmethod
    def _is_podman_available() -> bool:
        """Check if podman binary and socket are available."""
        from shutil import which  # noqa: PLC0415
        return which("podman") is not None

    @staticmethod
    def _get_real_image_digest(image_ref: str) -> str | None:
        """Get the digest of a real local image via 'podman images --format'.

        Returns the full digest (sha256:...) or None if image not found.
        """
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "podman", "images",
                "--filter", f"reference={image_ref}",
                "--format", "{{.Digest}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            digest = result.stdout.strip()
            if digest and digest.startswith("sha256:"):
                return digest
        return None

    def test_resolve_manifest_list_children_via_images_list_real_socket(self):
        """Real test: resolve manifest-list child digests using images.list().

        This test:
        1. Creates a real local manifest list with podman manifest create/add
        2. Calls _resolve_all_platforms_from_manifest_list against real socket
        3. Verifies all platforms are successfully resolved (not None)

        Requires podman and two real local images with distinct digests.
        """
        if not self._is_podman_available():
            skip("podman not available")

        if PodmanClient is None:
            skip("PodmanClient SDK not available")

        # Find two real local images to add to the manifest list
        result = subprocess.run(
            ["podman", "images", "--format", "{{.Repository}}:{{.Tag}}"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode != 0 or not result.stdout.strip():
            skip("No local images available to create test manifest list")

        images = [line.strip() for line in result.stdout.split("\n") if line.strip()]
        if len(images) < 2:
            skip("Need at least 2 local images to test manifest-list resolution")

        # Use first two available images
        image1 = images[0]
        image2 = images[1]
        test_manifest_name = "test-multiplatform-resolve"

        try:
            # Create a fresh manifest list
            subprocess.run(  # noqa: S603
                ["podman", "manifest", "rm", test_manifest_name],  # noqa: S607
                capture_output=True,
                timeout=10,
                check=False,
            )  # Clean up if it exists

            subprocess.run(  # noqa: S603
                ["podman", "manifest", "create", test_manifest_name],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            console.info(f"Created manifest list: {test_manifest_name}")

            # Add two images to the manifest list with synthetic platform annotations
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "podman", "manifest", "add",
                    test_manifest_name, image1,
                    "--os", "linux",
                    "--arch", "amd64",
                ],
                capture_output=True,
                timeout=10,
                check=True,
            )
            console.info(f"Added {image1} to manifest as linux/amd64")

            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "podman", "manifest", "add",
                    test_manifest_name, image2,
                    "--os", "linux",
                    "--arch", "arm64",
                ],
                capture_output=True,
                timeout=10,
                check=True,
            )
            console.info(f"Added {image2} to manifest as linux/arm64")

            # Now call the real function against the real socket
            with TemporaryDirectory() as tmpdir:
                result = package_service._resolve_all_platforms_from_manifest_list(
                    test_manifest_name,
                    tmpdir,
                )

                console.info(f"Resolution result: {result}")

                # Verify both platforms resolved successfully (not None)
                assert "linux/amd64" in result, f"linux/amd64 not in result: {result}"
                assert "linux/arm64" in result, f"linux/arm64 not in result: {result}"

                amd64_path = result.get("linux/amd64")
                arm64_path = result.get("linux/arm64")

                assert amd64_path is not None, "linux/amd64 resolved to None (digest lookup failed)"
                assert arm64_path is not None, "linux/arm64 resolved to None (digest lookup failed)"

                assert Path(amd64_path).exists(), f"Exported amd64 tar not found: {amd64_path}"
                assert Path(arm64_path).exists(), f"Exported arm64 tar not found: {arm64_path}"

                console.success("✓ Both platforms resolved successfully")
                console.info(f"  linux/amd64: {amd64_path}")
                console.info(f"  linux/arm64: {arm64_path}")

        finally:
            # Clean up the test manifest list
            with contextlib.suppress(Exception):
                subprocess.run(  # noqa: S603
                    ["podman", "manifest", "rm", test_manifest_name],  # noqa: S607
                    capture_output=True,
                    timeout=10,
                    check=False,
                )


class TestCreateOciImageLayoutTarAnnotations:
    """Tests for ref-name annotations in OCI image-layout tar creation."""

    @mark.skip("Bug 3: ref-name annotations not yet implemented")
    def test_single_platform_manifest_includes_ref_name_annotation(self):
        """Should add ref-name annotation to single-platform manifest in index.json."""
        with TemporaryDirectory() as tmpdir:
            # Create a minimal single-platform manifest
            manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {
                    "size": 1234,
                    "digest": "sha256:abcd1234567890",
                    "mediaType": "application/vnd.oci.empty.v1+json",
                },
                "layers": [],
            }

            # Mock OrasClient to provide blob downloads
            mock_oras = Mock()

            # Mock blob downloads (we won't actually write real blobs)
            def mock_download_blob(_ref, _digest, path):
                # Create empty blob file
                Path(path).write_bytes(b"")

            mock_oras.download_blob.side_effect = mock_download_blob

            # Mock blob digest verification to skip checks
            with patch("margot.services.package._verify_blob_digest"):
                # Create output tar path
                output_tar = Path(tmpdir) / "test.tar"
                image_ref = "myregistry.com/myapp:v1.0"

                # Call the function
                package_service._create_oci_image_layout_tar(
                    image_ref,
                    manifest,
                    mock_oras,
                    str(output_tar),
                )

            # Extract and verify index.json contains ref-name annotation
            with tar_open(str(output_tar), "r") as tar:
                # List members to find the correct path
                members = tar.getnames()
                # The tar contains a root directory, so index.json is at ./index.json or in a subdir
                index_path = None
                for member in members:
                    if member.endswith("index.json"):
                        index_path = member
                        break

                assert index_path is not None, f"index.json not found in tar. Members: {members}"

                index_member = tar.getmember(index_path)
                index_f = tar.extractfile(index_member)
                assert index_f is not None
                index_json = json_loads(index_f.read())

            # Verify structure
            assert "manifests" in index_json
            assert len(index_json["manifests"]) == 1
            manifest_entry = index_json["manifests"][0]

            # Verify annotations are present
            assert "annotations" in manifest_entry
            assert manifest_entry["annotations"].get("org.opencontainers.image.ref.name") == image_ref

    @mark.skip("Bug 3: ref-name annotations not yet implemented")
    def test_multi_platform_index_includes_ref_name_annotations(self):
        """Should add ref-name annotation to all entries in multi-platform index.json."""
        with TemporaryDirectory() as tmpdir:
            # Create a multi-platform index
            manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:amd64manifest123",
                        "size": 500,
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:arm64manifest456",
                        "size": 500,
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }

            # Mock OrasClient
            mock_oras = Mock()

            def mock_download_blob(_ref, digest, path):
                # For manifests, return a minimal valid manifest JSON
                if digest.startswith("sha256:") and "manifest" in digest:
                    manifest_content = {
                        "schemaVersion": 2,
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "config": {"digest": "sha256:config123", "size": 100, "mediaType": "application/vnd.oci.empty.v1+json"},
                        "layers": [],
                    }
                    Path(path).write_text(json_dumps(manifest_content))
                else:
                    Path(path).write_bytes(b"")

            mock_oras.download_blob.side_effect = mock_download_blob

            # Mock blob digest verification to skip checks
            with patch("margot.services.package._verify_blob_digest"):
                # Create output tar path
                output_tar = Path(tmpdir) / "test-multiarch.tar"
                image_ref = "docker.io/library/ubuntu:22.04"

                # Call the function
                package_service._create_oci_image_layout_tar(
                    image_ref,
                    manifest,
                    mock_oras,
                    str(output_tar),
                )

            # Extract and verify index.json contains ref-name annotations for all entries
            with tar_open(str(output_tar), "r") as tar:
                members = tar.getnames()
                index_path = None
                for member in members:
                    if member.endswith("index.json"):
                        index_path = member
                        break

                assert index_path is not None, f"index.json not found in tar. Members: {members}"

                index_member = tar.getmember(index_path)
                index_f = tar.extractfile(index_member)
                assert index_f is not None
                index_json = json_loads(index_f.read())

            # Verify structure
            assert "manifests" in index_json
            assert len(index_json["manifests"]) == 2

            # Verify both entries have ref-name annotation
            for i, entry in enumerate(index_json["manifests"]):
                assert "annotations" in entry, f"Manifest entry {i} missing annotations"
                assert entry["annotations"].get("org.opencontainers.image.ref.name") == image_ref

    @mark.skip("Bug 3: ref-name annotations not yet implemented")
    def test_multi_platform_preserves_existing_annotations(self):
        """Should preserve existing annotations while adding ref-name to multi-platform index."""
        with TemporaryDirectory() as tmpdir:
            # Create a multi-platform index with existing annotations
            manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:amd64manifest123",
                        "size": 500,
                        "platform": {"os": "linux", "architecture": "amd64"},
                        "annotations": {
                            "custom.key": "custom.value",
                            "another.key": "another.value",
                        },
                    },
                ],
            }

            # Mock OrasClient
            mock_oras = Mock()

            def mock_download_blob(_ref, digest, path):
                if digest.startswith("sha256:") and "manifest" in digest:
                    from json import dumps as json_dumps  # noqa: PLC0415
                    manifest_content = {
                        "schemaVersion": 2,
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "config": {"digest": "sha256:config123", "size": 100, "mediaType": "application/vnd.oci.empty.v1+json"},
                        "layers": [],
                    }
                    Path(path).write_text(json_dumps(manifest_content))
                else:
                    Path(path).write_bytes(b"")

            mock_oras.download_blob.side_effect = mock_download_blob

            # Mock blob digest verification to skip checks
            with patch("margot.services.package._verify_blob_digest"):
                # Create output tar path
                output_tar = Path(tmpdir) / "test-preserve-annot.tar"
                image_ref = "myapp:latest"

                # Call the function
                package_service._create_oci_image_layout_tar(
                    image_ref,
                    manifest,
                    mock_oras,
                    str(output_tar),
                )

            # Extract and verify index.json
            with tar_open(str(output_tar), "r") as tar:
                members = tar.getnames()
                index_path = None
                for member in members:
                    if member.endswith("index.json"):
                        index_path = member
                        break

                assert index_path is not None, f"index.json not found in tar. Members: {members}"

                index_member = tar.getmember(index_path)
                index_f = tar.extractfile(index_member)
                assert index_f is not None
                index_json = json_loads(index_f.read())

            # Verify structure
            manifest_entry = index_json["manifests"][0]
            annotations = manifest_entry.get("annotations", {})

            # Verify custom annotations are preserved AND ref-name is added
            assert annotations.get("custom.key") == "custom.value"
            assert annotations.get("another.key") == "another.value"
            assert annotations.get("org.opencontainers.image.ref.name") == image_ref



class TestCreateOciImageLayoutTarRealLoad:
    """Real round-trip tests using actual podman load (not mocked)."""

    @staticmethod
    def _is_podman_available() -> bool:
        """Check if podman binary is available."""
        from shutil import which  # noqa: PLC0415
        return which("podman") is not None

    @staticmethod
    def _parse_loaded_image_ref(podman_output: str) -> str | None:
        """Parse loaded image reference from podman load output.

        Expected format: 'Loaded image: <ref>' or 'Loaded image: <digest>'
        """
        for line in podman_output.split("\n"):
            if "Loaded image:" in line:
                parts = line.split("Loaded image:")
                if len(parts) > 1:
                    return parts[1].strip()
        return None

    @staticmethod
    def _create_minimal_layer_blob() -> tuple[bytes, str]:
        """Create a minimal valid OCI layer blob (gzipped tar with one small file).

        Returns a tuple of (gzipped_blob_bytes, diff_id) where diff_id is the sha256
        of the uncompressed tar (used in config.rootfs.diff_ids).
        """
        # Create a minimal tar with one small file
        tar_buffer = BytesIO()
        with tar_open(fileobj=tar_buffer, mode="w") as tar:
            # Add a single small file to the tar
            file_content = b"minimal layer content"
            info = TarInfo(name="minimal.txt")
            info.size = len(file_content)
            tar.addfile(tarinfo=info, fileobj=BytesIO(file_content))

        tar_bytes = tar_buffer.getvalue()

        # Compute the diff_id (hash of uncompressed tar)
        diff_id = f"sha256:{sha256_hash(tar_bytes).hexdigest()}"

        # Gzip the tar
        gzip_buffer = BytesIO()
        with gzip.GzipFile(fileobj=gzip_buffer, mode="wb") as gz:
            gz.write(tar_bytes)

        return gzip_buffer.getvalue(), diff_id

    def _build_manifest_with_layer(
        self, layer_blob: bytes, layer_diff_id: str
    ) -> tuple[dict, str, str]:
        """Build a minimal OCI manifest with a layer blob.

        Returns: (manifest dict, config_json str, config_digest str)
        """
        config_blob = {
            "architecture": "amd64",
            "config": {
                "Env": ["PATH=/usr/sbin:/usr/bin:/sbin:/bin"],
                "Cmd": ["/bin/sh"],
            },
            "rootfs": {"type": "layers", "diff_ids": [layer_diff_id]},
            "history": [],
        }

        config_json = json_dumps(config_blob, separators=(",", ":"), sort_keys=True)
        config_digest = f"sha256:{sha256_hash(config_json.encode()).hexdigest()}"
        layer_digest = f"sha256:{sha256_hash(layer_blob).hexdigest()}"

        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "size": len(config_json.encode()),
                "digest": config_digest,
                "mediaType": "application/vnd.oci.image.config.v1+json",
            },
            "layers": [
                {
                    "size": len(layer_blob),
                    "digest": layer_digest,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                }
            ],
        }

        return manifest, config_json, config_digest

    def _run_podman_load(
        self, output_tar: Path, test_image_ref: str
    ) -> str | None:
        """Run 'podman load -i <tar>' and return the loaded reference or None.

        Raises AssertionError if podman load fails for structural reasons.
        Calls skip() if podman daemon is unavailable.
        """
        result = subprocess.run(  # noqa: S603
            ["podman", "load", "-i", str(output_tar)],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        # Check exit code
        if result.returncode != 0:
            console.debug(f"podman load stderr: {result.stderr}")
            # Only skip for connection/socket errors, not for structural errors
            if "not available" in result.stderr or "cannot connect" in result.stderr:
                skip(f"podman daemon not available: {result.stderr}")
            else:
                # Real structural error — let it fail loudly to expose fixture bugs
                raise AssertionError(
                    f"podman load failed with structural error (not env unavailability). "
                    f"stderr: {result.stderr}"
                )

        # Parse loaded image reference from output
        loaded_ref = self._parse_loaded_image_ref(result.stdout + result.stderr)

        if loaded_ref is None:
            # Sometimes podman load doesn't output anything useful on success
            # In that case, try to query the image
            query_result = subprocess.run(  # noqa: S603
                ["podman", "image", "exists", test_image_ref],  # noqa: S607
                capture_output=True,
                timeout=10,
                check=False,
            )
            if query_result.returncode == 0:
                # Image exists with the original tag, which is what we want
                console.info(f"✓ podman loaded image with tag: {test_image_ref}")
                return test_image_ref
            skip("Could not determine if image was loaded")

        return loaded_ref

    def test_real_podman_load_single_platform_preserves_tag(self):
        """Real test: podman load should preserve the image tag from ref-name annotation.

        This test:
        1. Creates a real OCI image layout tar with ref-name annotations
        2. Runs actual 'podman load -i <tar>' against it
        3. Verifies the loaded image retains the original tag (not bare digest)

        This requires podman to be available in the test environment.
        """
        if not self._is_podman_available():
            skip("podman not available")

        with TemporaryDirectory() as tmpdir:
            # Create layer and manifest
            layer_blob, layer_diff_id = self._create_minimal_layer_blob()
            manifest, config_json, config_digest = self._build_manifest_with_layer(
                layer_blob, layer_diff_id
            )
            layer_digest = f"sha256:{sha256_hash(layer_blob).hexdigest()}"

            # Mock OrasClient to download real blobs
            mock_oras = Mock()

            def mock_download_blob(_ref, digest, path):
                if digest == config_digest:
                    Path(path).write_text(config_json)
                elif digest == layer_digest:
                    Path(path).write_bytes(layer_blob)
                else:
                    Path(path).write_bytes(b"")

            mock_oras.download_blob.side_effect = mock_download_blob

            # Create OCI layout tar
            test_image_ref = "localhost/test-image-bug3:v1.0.0"
            output_tar = Path(tmpdir) / "test-image.tar"

            # Mock blob digest verification to skip checks
            with patch("margot.services.package._verify_blob_digest"):
                package_service._create_oci_image_layout_tar(
                    test_image_ref,
                    manifest,
                    mock_oras,
                    str(output_tar),
                )

            assert output_tar.exists(), "OCI layout tar not created"

            # Run podman load and verify tag is preserved
            loaded_ref = None
            try:
                loaded_ref = self._run_podman_load(output_tar, test_image_ref)

                # The key assertion: loaded ref should NOT be a bare digest
                # It should be the tagged reference we provided (or similar)
                assert loaded_ref is not None
                assert not loaded_ref.startswith("sha256:"), (
                    f"podman load returned bare digest {loaded_ref}, expected tagged ref. "
                    f"This means ref-name annotation was not found in index.json."
                )

                console.info(f"✓ podman loaded image as: {loaded_ref} (not a bare digest)")

            except subprocess.TimeoutExpired as e:
                skip(f"podman load timed out: {e}")
            except FileNotFoundError as e:
                skip(f"podman binary not in PATH: {e}")
            finally:
                # Clean up loaded images if they exist
                if loaded_ref is not None:
                    with contextlib.suppress(Exception):
                        subprocess.run(  # noqa: S603
                            ["podman", "rmi", loaded_ref],  # noqa: S607
                            capture_output=True,
                            timeout=10,
                            check=False,
                        )

