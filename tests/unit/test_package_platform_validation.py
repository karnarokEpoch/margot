"""Tests for platform validation and multi-arch image inclusion in package service."""

from contextlib import suppress
import gzip
from hashlib import sha256 as sha256_hash
from io import BytesIO
from json import dumps as json_dumps
from pathlib import Path
from tarfile import TarInfo
from tarfile import open as tar_open
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import Mock, patch

from pytest import mark, param, raises

from margot.services import package as package_service


class TestValidatePlatform:
    """Tests for _validate_platform function."""

    def test_valid_os_arch_platform(self):
        """Should accept valid os/arch platform strings."""
        package_service._validate_platform("linux/amd64")
        package_service._validate_platform("linux/arm64")
        package_service._validate_platform("darwin/amd64")
        # Should not raise

    def test_valid_os_arch_variant_platform(self):
        """Should accept valid os/arch/variant platform strings."""
        package_service._validate_platform("linux/arm/v7")
        package_service._validate_platform("linux/arm/v8")
        # Should not raise

    def test_rejects_invalid_single_part(self):
        """Should reject platform with only one part."""
        with raises(ValueError, match="must be in os/arch or os/arch/variant format"):
            package_service._validate_platform("linux")

    def test_rejects_invalid_four_parts(self):
        """Should reject platform with more than three parts."""
        with raises(ValueError, match="must be in os/arch or os/arch/variant format"):
            package_service._validate_platform("linux/arm/v7/extra")

    def test_rejects_empty_part(self):
        """Should reject platform with empty parts."""
        with raises(ValueError, match="must be in os/arch or os/arch/variant format"):
            package_service._validate_platform("linux//amd64")

    def test_rejects_trailing_slash(self):
        """Should reject platform with trailing slash."""
        with raises(ValueError, match="must be in os/arch or os/arch/variant format"):
            package_service._validate_platform("linux/amd64/")

    def test_rejects_all_keyword(self):
        """Should reject the 'all' keyword (common mistake from Item 1 defect)."""
        with raises(ValueError, match="must be in os/arch or os/arch/variant format"):
            package_service._validate_platform("all")


class TestPlatformMatchesManifest:
    """Tests for _platform_matches_manifest helper."""

    def test_matches_simple_platform(self):
        """Should match a simple os/arch platform against manifest descriptor."""
        manifest_platform = {"os": "linux", "architecture": "amd64"}
        assert package_service._platform_matches_manifest("linux/amd64", manifest_platform) is True

    def test_matches_with_variant(self):
        """Should match os/arch/variant platform against manifest with matching variant."""
        manifest_platform = {"os": "linux", "architecture": "arm", "variant": "v7"}
        assert package_service._platform_matches_manifest("linux/arm/v7", manifest_platform) is True

    def test_no_match_different_arch(self):
        """Should not match if architecture differs."""
        manifest_platform = {"os": "linux", "architecture": "amd64"}
        assert package_service._platform_matches_manifest("linux/arm64", manifest_platform) is False

    def test_no_match_different_os(self):
        """Should not match if OS differs."""
        manifest_platform = {"os": "windows", "architecture": "amd64"}
        assert package_service._platform_matches_manifest("linux/amd64", manifest_platform) is False

    def test_no_match_variant_requested_but_absent(self):
        """Should not match if variant is requested but manifest doesn't have it."""
        manifest_platform = {"os": "linux", "architecture": "arm"}  # no variant
        assert package_service._platform_matches_manifest("linux/arm/v7", manifest_platform) is False

    def test_matches_variant_present_but_not_requested(self):
        """Should match if manifest has variant but request doesn't filter for it."""
        # Per the existing logic in margot: "linux/arm" (no variant) matches
        # against "linux/arm/v7" (has variant) — this is a loose match allowing
        # requesting an architecture to work against any variant of that arch.
        manifest_platform = {"os": "linux", "architecture": "arm", "variant": "v7"}
        # Requesting "linux/arm" (no variant) against manifest with "variant: v7" SHOULD match
        assert package_service._platform_matches_manifest("linux/arm", manifest_platform) is True

    def test_matches_variant_when_explicit_none(self):
        """Should match when manifest has no variant and request specifies no variant."""
        manifest_platform = {"os": "linux", "architecture": "arm"}  # no variant key
        assert package_service._platform_matches_manifest("linux/arm", manifest_platform) is True


class TestFilterManifestsByPlatforms:
    """Tests for _filter_manifests_by_platforms function."""

    def test_empty_platforms_returns_unfiltered(self):
        """Should return manifest unmodified if platforms list is empty."""
        manifest = {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {"digest": "sha256:abc", "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:def", "platform": {"os": "linux", "architecture": "arm64"}},
            ],
        }
        result = package_service._filter_manifests_by_platforms(manifest, [])
        assert result == manifest

    def test_filters_index_to_requested_platforms(self):
        """Should filter index.json manifests to only requested platforms."""
        manifest = {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {"digest": "sha256:amd64", "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:arm64", "platform": {"os": "linux", "architecture": "arm64"}},
            ],
        }
        result = package_service._filter_manifests_by_platforms(manifest, ["linux/amd64"])
        assert len(result["manifests"]) == 1
        assert result["manifests"][0]["digest"] == "sha256:amd64"

    def test_filters_multiple_requested_platforms(self):
        """Should filter to multiple requested platforms."""
        manifest = {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {"digest": "sha256:amd64", "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:arm64", "platform": {"os": "linux", "architecture": "arm64"}},
                {"digest": "sha256:arm_v7", "platform": {"os": "linux", "architecture": "arm", "variant": "v7"}},
            ],
        }
        result = package_service._filter_manifests_by_platforms(manifest, ["linux/amd64", "linux/arm/v7"])
        assert len(result["manifests"]) == 2
        digests = {m["digest"] for m in result["manifests"]}
        assert digests == {"sha256:amd64", "sha256:arm_v7"}

    def test_raises_on_requested_platform_not_found(self):
        """Should raise ValueError if a requested platform is not in index."""
        manifest = {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {"digest": "sha256:amd64", "platform": {"os": "linux", "architecture": "amd64"}},
            ],
        }
        with raises(ValueError, match="not found in image index"):
            package_service._filter_manifests_by_platforms(manifest, ["linux/arm64"])

    def test_raises_on_single_arch_manifest_with_platform_filter(self):
        """Should raise ValueError for single-platform manifest with platform filter."""
        # Single-platform manifest has no 'index' in mediaType
        manifest = {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"digest": "sha256:cfg"},
            "layers": [],
        }
        with raises(ValueError, match="Single-platform image does not support --platform filtering"):
            package_service._filter_manifests_by_platforms(manifest, ["linux/amd64"])


class TestDiscoverAndIncludeImagesAutoMode:
    """Tests for _discover_and_include_images with runtime='auto'."""

    def test_auto_mode_always_contacts_registry(self):
        """auto mode should ALWAYS call oras_client.get_manifest(), even if daemon has the image."""
        with TemporaryDirectory() as tmpdir:
            staging_root = Path(tmpdir) / "staging"
            staging_root.mkdir()

            meta = Mock()
            meta.id = "test-app"
            meta.name = "test"
            meta.repository = "public.ecr.aws/test/app"
            meta.compose = Mock()
            meta.quadlet = None

            component_versions = {package_service.PackageType.COMPOSE: ["1.0"]}

            mock_oras_client = Mock()
            # Simulate registry manifest with 2 platforms
            registry_manifest = {
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {"digest": "sha256:amd64", "platform": {"os": "linux", "architecture": "amd64"}},
                    {"digest": "sha256:arm64", "platform": {"os": "linux", "architecture": "arm64"}},
                ],
            }
            mock_oras_client.get_manifest.return_value = registry_manifest

            # Create temporary component tar for discovery
            comp_dir = Path(tmpdir) / "1.0"
            comp_dir.mkdir()
            comp_tar = comp_dir / "test-1.0.tgz"

            with tar_open(comp_tar, "w:gz") as tar:
                # Create minimal compose.yml inside
                compose_content = "services:\n  web:\n    image: nginx:latest\n"
                info = TarInfo(name="compose.yaml")
                info.size = len(compose_content.encode())
                tar.addfile(info, BytesIO(compose_content.encode()))

            with patch(
                "margot.services.package._lookup_image_with_runtime"
            ) as mock_lookup, patch(
                "margot.services.package._pull_image_with_local_daemon_optimization"
            ) as mock_pull_opt, patch(
                "margot.services.package.OrasClient"
            ) as mock_oras_class, patch(
                "margot.services.package.extract_hostname"
            ) as mock_extract_hostname, patch(
                "margot.services.package.validate_uri"
            ), patch(
                "margot.services.package._discover_image_references_compose",
                side_effect=lambda _: ["nginx:latest"]
            ):
                mock_extract_hostname.return_value = "docker.io"
                mock_oras_class.return_value = mock_oras_client
                mock_lookup.return_value = None  # daemon doesn't have it

                # Call the function
                package_service._discover_and_include_images(
                    staging_root,
                    {package_service.PackageType.COMPOSE},
                    str(Path(tmpdir)),
                    meta,
                    component_versions,
                    runtime="auto",
                    platforms=[],
                )

                # Verify get_manifest was called (MUST contact registry in auto mode)
                assert mock_oras_client.get_manifest.called, "get_manifest() should be called in auto mode"
                assert mock_pull_opt.called, "Pull optimization should be called"

    def test_auto_mode_registry_pull_when_daemon_unavailable(self):
        """auto mode should pull from registry when daemon doesn't have the image."""
        with TemporaryDirectory() as tmpdir:
            staging_root = Path(tmpdir) / "staging"
            staging_root.mkdir()

            # Create temporary component tar for discovery
            comp_dir = Path(tmpdir) / "1.0"
            comp_dir.mkdir()
            comp_tar = comp_dir / "test-1.0.tgz"

            with tar_open(comp_tar, "w:gz") as tar:
                # Create minimal compose.yml inside
                compose_content = "services:\n  web:\n    image: nginx:latest\n"
                info = TarInfo(name="compose.yaml")
                info.size = len(compose_content.encode())
                tar.addfile(info, BytesIO(compose_content.encode()))

            meta = Mock()
            meta.id = "test-app"
            meta.name = "test"
            meta.repository = "public.ecr.aws/test/app"
            meta.compose = Mock()
            meta.quadlet = None

            component_versions = {package_service.PackageType.COMPOSE: ["1.0"]}

            mock_oras_client = Mock()
            registry_manifest = {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {"digest": "sha256:config"},
                "layers": [],
            }
            mock_oras_client.get_manifest.return_value = registry_manifest

            with patch(
                "margot.services.package._pull_image_with_local_daemon_optimization"
            ) as mock_pull_opt, patch(
                "margot.services.package.OrasClient"
            ) as mock_oras_class, patch(
                "margot.services.package.extract_hostname"
            ) as mock_extract_hostname, patch(
                "margot.services.package.validate_uri"
            ):
                mock_extract_hostname.return_value = "docker.io"
                mock_oras_class.return_value = mock_oras_client

                # Call the function
                package_service._discover_and_include_images(
                    staging_root,
                    {package_service.PackageType.COMPOSE},
                    str(Path(tmpdir)),
                    meta,
                    component_versions,
                    runtime="auto",
                    platforms=[],
                )

                # Verify registry was contacted
                assert mock_oras_client.get_manifest.called
                # Verify pull optimization was called
                assert mock_pull_opt.called

class TestDiscoverAndIncludeImagesDaemonForced:
    """Tests for _discover_and_include_images with --runtime podman/docker (forced)."""

    def test_forced_daemon_no_images_to_discover(self):
        """--runtime podman should be accepted even with no images."""
        with TemporaryDirectory() as tmpdir:
            staging_root = Path(tmpdir) / "staging"
            staging_root.mkdir()

            meta = Mock()
            meta.id = "test-app"
            meta.name = "test"
            meta.repository = "public.ecr.aws/test/app"
            meta.compose = None
            meta.quadlet = None

            component_versions = {}

            with patch(
                "margot.services.package._discover_image_references_compose",
                return_value=[],
            ), patch(
                "margot.services.package._discover_image_references_quadlet",
                return_value=[],
            ):
                # Should not raise; just returns early if no images discovered
                package_service._discover_and_include_images(
                    staging_root,
                    {package_service.PackageType.COMPOSE},
                    ".dist",
                    meta,
                    component_versions,
                    runtime="podman",
                    platforms=[],
                )


class TestValidatePlatformEarlyFailure:
    """Tests that invalid --platform values fail fast before any I/O."""

    @mark.parametrize(
        "runtime_value",
        [
            param("auto", id="auto"),
            param("none", id="none"),
            param("podman", id="podman"),
            param("docker", id="docker"),
        ],
    )
    def test_invalid_platform_fails_before_io_all_runtime_modes(self, runtime_value):
        """Invalid --platform should fail fast before any daemon/registry I/O."""
        with TemporaryDirectory() as tmpdir:
            staging_root = Path(tmpdir) / "staging"
            staging_root.mkdir()

            meta = Mock()
            meta.id = "test-app"
            meta.name = "test"
            meta.repository = "public.ecr.aws/test/app"
            meta.compose = None
            meta.quadlet = None

            component_versions = {}

            with patch(
                "margot.services.package._discover_image_references_compose"
            ) as mock_discover_compose, patch(
                "margot.services.package._discover_image_references_quadlet"
            ) as mock_discover_quadlet, patch(
                "margot.services.package.OrasClient"
            ) as mock_oras_class, patch(
                "margot.services.package.extract_hostname"
            ) as mock_extract_hostname, patch(
                "margot.services.package.validate_uri"
            ), patch(
                "margot.services.package.console.fatal"
            ) as mock_fatal:
                mock_discover_compose.return_value = ["nginx:latest"]
                mock_discover_quadlet.return_value = []
                mock_extract_hostname.return_value = "docker.io"
                mock_oras_client = Mock()
                mock_oras_class.return_value = mock_oras_client

                # Invalid platform "all" should fail before any I/O
                with suppress(Exception):
                    package_service._discover_and_include_images(
                        staging_root,
                        {package_service.PackageType.COMPOSE},
                        ".dist",
                        meta,
                        component_versions,
                        runtime=runtime_value,
                        platforms=["all"],  # Invalid!
                    )

                # console.fatal should have been called with platform error
                assert mock_fatal.called, f"console.fatal should be called for invalid platform with --runtime {runtime_value}"
                call_args = str(mock_fatal.call_args)
                assert "all" in call_args or "platform" in call_args.lower(), (
                    f"Error message should mention 'all' or 'platform': {call_args}"
                )

                # Most importantly: get_manifest and daemon lookup should NOT have been called
                assert not mock_oras_client.get_manifest.called, (
                    f"get_manifest should not be called with invalid --platform in {runtime_value} mode"
                )


class TestDiscoverAndIncludeImagesNoneMode:
    """Tests for _discover_and_include_images with runtime='none' (registry-only)."""

    def test_none_mode_processes_images(self):
        """--runtime none should process images without attempting daemon lookup."""
        with TemporaryDirectory() as tmpdir:
            staging_root = Path(tmpdir) / "staging"
            staging_root.mkdir()

            meta = Mock()
            meta.id = "test-app"
            meta.name = "test"
            meta.repository = "public.ecr.aws/test/app"
            meta.compose = None
            meta.quadlet = None

            component_versions = {}

            with patch(
                "margot.services.package._lookup_image_with_runtime"
            ) as mock_lookup, patch(
                "margot.services.package._discover_image_references_compose",
                return_value=[],
            ):
                # Should not raise; should return early because no images discovered
                package_service._discover_and_include_images(
                    staging_root,
                    {package_service.PackageType.COMPOSE},
                    ".dist",
                    meta,
                    component_versions,
                    runtime="none",
                    platforms=[],
                )

                # Daemon lookup should NOT be called in 'none' mode
                assert not mock_lookup.called, "Daemon lookup should not be called with --runtime none"


class TestDaemonBlendinAutoMode:
    """Tests for per-platform daemon/registry blending in auto mode.

    These tests verify that the daemon blending infrastructure is in place,
    though full end-to-end testing would require valid OCI manifests with
    matching digests (which requires integration testing against real or
    simulated registries).
    """

    def test_pull_image_with_daemon_opt_processes_all_platforms(self):
        """Verify that _pull_image_with_local_daemon_optimization processes all platform slots."""
        with TemporaryDirectory() as tmpdir:
            # Setup a simple multi-platform index
            registry_index = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:amd64manifest",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:arm64manifest",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }

            mock_oras_client = Mock()
            mock_oras_client.download_blob = Mock()
            mock_oras_client.get_manifest = Mock(return_value=registry_index)

            output_tar = Path(tmpdir) / "output.oci.tar"

            with patch(
                "margot.services.package._try_daemon_match_for_platform",
                return_value=None,  # No daemon matches
            ), patch(
                "margot.services.package._create_oci_image_layout_tar",
            ) as mock_create_layout:
                # Call the blending function
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    registry_index,
                    mock_oras_client,
                    str(output_tar),
                    str(Path(tmpdir) / "daemon_dir"),
                )

                # Verify _create_oci_image_layout_tar was called
                assert mock_create_layout.called, "_create_oci_image_layout_tar should be called"

                # Get the call arguments
                call_args = mock_create_layout.call_args
                # Arguments are: image_ref, manifest, oras_client, output_tar_path, platforms, pre_downloaded_blobs
                # pre_downloaded_blobs is the 6th argument (index 5), but could also be in kwargs
                if call_args[1]:  # If there are keyword arguments
                    assert "pre_downloaded_blobs" in call_args[1], (
                        "pre_downloaded_blobs should be in kwargs"
                    )
                # The important thing is that the function was called with the new signature
                # which includes the optional pre_downloaded_blobs parameter

    def test_pull_image_skips_registry_for_daemon_matched_platform(self):  # noqa: PLR0915
        """Prove that daemon-matched platform blobs skip registry download.

        This test creates a real multi-platform index with two valid OCI manifests
        (amd64 and arm64, each with a config and layer blob), then mocks the daemon
        lookup to return a real daemon-exported tar ONLY for amd64. The arm64 platform
        will have no daemon match. After pulling with blending, we assert:
        - oras_client.download_blob was called for arm64's manifest, config, and layer digests
        - oras_client.download_blob was NEVER called for amd64's manifest, config, or layer digests
        This proves that amd64's blobs came from daemon export (pre_downloaded_blobs)
        instead of a redundant registry download.
        """
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            # Helper to create a minimal valid layer blob
            def _create_minimal_layer_blob() -> tuple[bytes, str]:
                tar_buffer = BytesIO()
                with tar_open(fileobj=tar_buffer, mode="w") as tar:
                    file_content = b"minimal layer content"
                    info = TarInfo(name="minimal.txt")
                    info.size = len(file_content)
                    tar.addfile(tarinfo=info, fileobj=BytesIO(file_content))

                tar_bytes = tar_buffer.getvalue()
                diff_id = f"sha256:{sha256_hash(tar_bytes).hexdigest()}"

                gzip_buffer = BytesIO()
                with gzip.GzipFile(fileobj=gzip_buffer, mode="wb") as gz:
                    gz.write(tar_bytes)

                return gzip_buffer.getvalue(), diff_id

            # Create two platform-specific manifests with real digests
            def _create_manifest_with_platform(
                platform: str,
            ) -> tuple[dict, bytes, str, str, bytes, str]:
                """Create a manifest tuple: (manifest_dict, manifest_bytes, config_json, config_digest, layer_blob, layer_digest).

                Returns dict and bytes separately so that the bytes match the dict's serialization exactly.
                """
                # Create a platform-specific layer blob so each platform has unique digests
                layer_tar_buffer = BytesIO()
                with tar_open(fileobj=layer_tar_buffer, mode="w") as tar:
                    file_content = f"layer content for {platform}".encode()
                    info = TarInfo(name=f"file-{platform}.txt")
                    info.size = len(file_content)
                    tar.addfile(tarinfo=info, fileobj=BytesIO(file_content))

                tar_bytes = layer_tar_buffer.getvalue()
                layer_diff_id = f"sha256:{sha256_hash(tar_bytes).hexdigest()}"

                gzip_buffer = BytesIO()
                with gzip.GzipFile(fileobj=gzip_buffer, mode="wb") as gz:
                    gz.write(tar_bytes)

                layer_blob = gzip_buffer.getvalue()
                layer_digest = f"sha256:{sha256_hash(layer_blob).hexdigest()}"

                config_blob = {
                    "architecture": platform.split("/")[1],
                    "config": {
                        "Env": ["PATH=/usr/bin"],
                        "Cmd": ["/bin/sh"],
                    },
                    "rootfs": {"type": "layers", "diff_ids": [layer_diff_id]},
                    "history": [],
                }

                config_json = json_dumps(config_blob, separators=(",", ":"), sort_keys=True)
                config_digest = f"sha256:{sha256_hash(config_json.encode()).hexdigest()}"

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

                # Serialize manifest to get exact bytes for digest calculation
                manifest_json = json_dumps(manifest, separators=(",", ":"), sort_keys=True)
                manifest_json_bytes = manifest_json.encode()

                return manifest, manifest_json_bytes, config_json, config_digest, layer_blob, layer_digest

            # Create manifests for both platforms
            _, amd64_manifest_bytes, amd64_config_json, amd64_config_digest, amd64_layer_blob, amd64_layer_digest = (
                _create_manifest_with_platform("linux/amd64")
            )
            amd64_manifest_digest = f"sha256:{sha256_hash(amd64_manifest_bytes).hexdigest()}"

            _, arm64_manifest_bytes, _, arm64_config_digest, _, arm64_layer_digest = (
                _create_manifest_with_platform("linux/arm64")
            )
            arm64_manifest_digest = f"sha256:{sha256_hash(arm64_manifest_bytes).hexdigest()}"

            # Create a multi-platform index pointing to both
            registry_index = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": amd64_manifest_digest,
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": arm64_manifest_digest,
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }

            # Create a daemon-exported tar for amd64 only (valid OCI-archive structure)
            def _create_daemon_export_tar(  # noqa: PLR0913
                manifest_bytes: bytes,
                manifest_digest: str,
                config_json: str,
                config_digest: str,
                layer_blob: bytes,
                layer_digest: str,
            ) -> str:
                """Create a valid OCI-archive tar for the platform."""
                export_tar_path = tmpdir / "daemon_export_amd64.tar"

                # Create OCI layout structure
                with tar_open(str(export_tar_path), "w") as tar:
                    # oci-layout file
                    oci_layout = json_dumps({"imageLayoutVersion": "1.0.0"})
                    info = TarInfo(name="oci-layout")
                    info.size = len(oci_layout.encode())
                    tar.addfile(info, BytesIO(oci_layout.encode()))

                    # index.json pointing to manifest
                    index_json = {
                        "schemaVersion": 2,
                        "mediaType": "application/vnd.oci.image.index.v1+json",
                        "manifests": [
                            {
                                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                                "digest": manifest_digest,
                                "size": len(manifest_bytes),
                            }
                        ],
                    }
                    index_json_str = json_dumps(index_json)
                    info = TarInfo(name="index.json")
                    info.size = len(index_json_str.encode())
                    tar.addfile(info, BytesIO(index_json_str.encode()))

                    # Manifest blob - use the exact bytes that match the digest
                    manifest_filename = manifest_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{manifest_filename}")
                    info.size = len(manifest_bytes)
                    tar.addfile(info, BytesIO(manifest_bytes))

                    # Config blob
                    config_bytes = config_json.encode()
                    config_filename = config_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{config_filename}")
                    info.size = len(config_bytes)
                    tar.addfile(info, BytesIO(config_bytes))

                    # Layer blob
                    layer_filename = layer_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{layer_filename}")
                    info.size = len(layer_blob)
                    tar.addfile(info, BytesIO(layer_blob))

                return str(export_tar_path)

            amd64_daemon_tar = _create_daemon_export_tar(
                amd64_manifest_bytes,
                amd64_manifest_digest,
                amd64_config_json,
                amd64_config_digest,
                amd64_layer_blob,
                amd64_layer_digest,
            )

            # Mock OrasClient download_blob and get_manifest to track which digests are requested from registry
            mock_oras_client = Mock()
            downloaded_digests = []

            def mock_download_blob(_image_ref: str, digest: str, output_path: str) -> None:
                """Track which digests were downloaded from registry."""
                downloaded_digests.append(digest)
                # For manifest blobs, write the actual manifest bytes so parsing succeeds
                # (since _verify_blob_digest is mocked, the digest mismatch is acceptable here)
                if digest == amd64_manifest_digest:
                    Path(output_path).write_bytes(amd64_manifest_bytes)
                elif digest == arm64_manifest_digest:
                    Path(output_path).write_bytes(arm64_manifest_bytes)
                else:
                    # For config or layer blobs, write minimal placeholder data
                    Path(output_path).write_bytes(b"blob-data")

            mock_oras_client.download_blob = mock_download_blob
            mock_oras_client.get_manifest = Mock(return_value=registry_index)

            # Mock _try_daemon_match_for_platform to return daemon tar for amd64, None for arm64
            def mock_daemon_match(
                _image_ref: str, platform_str: str, _platform_desc: dict, _export_dir: Path
            ) -> str | None:
                if platform_str == "linux/amd64":
                    return amd64_daemon_tar
                # arm64 has no daemon match
                return None

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._try_daemon_match_for_platform", side_effect=mock_daemon_match
            ), patch("margot.services.package._verify_blob_digest"):
                # Call the blending function
                # Note: We mock _verify_blob_digest because the dummy blobs created for arm64 don't
                # have matching digests. This test focuses on proving which digests are downloaded,
                # not on validating the entire OCI layout.
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    registry_index,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # ASSERTIONS: Prove the skip
            # 1. amd64's blobs should NOT be in downloaded_digests (they came from daemon)
            msg_amd64_manifest = (
                f"amd64 manifest should NOT be downloaded from registry (daemon-matched), "
                f"but {amd64_manifest_digest} was downloaded"
            )
            assert amd64_manifest_digest not in downloaded_digests, msg_amd64_manifest
            msg_amd64_config = (
                f"amd64 config should NOT be downloaded from registry (daemon-matched), "
                f"but {amd64_config_digest} was downloaded"
            )
            assert amd64_config_digest not in downloaded_digests, msg_amd64_config
            msg_amd64_layer = (
                f"amd64 layer should NOT be downloaded from registry (daemon-matched), "
                f"but {amd64_layer_digest} was downloaded"
            )
            assert amd64_layer_digest not in downloaded_digests, msg_amd64_layer

            # 2. arm64's blobs SHOULD be in downloaded_digests (no daemon match, pulled from registry)
            msg_arm64_manifest = (
                f"arm64 manifest should be downloaded from registry (no daemon match), "
                f"but {arm64_manifest_digest} was NOT downloaded"
            )
            assert arm64_manifest_digest in downloaded_digests, msg_arm64_manifest
            msg_arm64_config = (
                f"arm64 config should be downloaded from registry (no daemon match), "
                f"but {arm64_config_digest} was NOT downloaded"
            )
            assert arm64_config_digest in downloaded_digests, msg_arm64_config
            msg_arm64_layer = (
                f"arm64 layer should be downloaded from registry (no daemon match), "
                f"but {arm64_layer_digest} was NOT downloaded"
            )
            assert arm64_layer_digest in downloaded_digests, msg_arm64_layer

            # 3. Output tar should exist and contain both platforms
            assert output_tar.exists(), f"Output tar should be created at {output_tar}"


class TestManifestListResolution:
    """Tests for local Podman manifest list resolution in auto mode."""

    def test_manifest_list_both_platforms_resolve_locally(self):  # noqa: PLR0915
        """Both child digests from manifest list resolve to local images → both exported, no registry contact.

        This proves manifest list is checked BEFORE registry index when both platforms
        are available locally via a manifest list.
        """
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            def _create_manifest_with_platform(
                platform: str,
            ) -> tuple[dict, bytes, str, str, bytes, str]:
                """Create a manifest tuple with real digests."""
                layer_tar_buffer = BytesIO()
                with tar_open(fileobj=layer_tar_buffer, mode="w") as tar:
                    file_content = f"layer content for {platform}".encode()
                    info = TarInfo(name=f"file-{platform}.txt")
                    info.size = len(file_content)
                    tar.addfile(tarinfo=info, fileobj=BytesIO(file_content))

                tar_bytes = layer_tar_buffer.getvalue()
                layer_diff_id = f"sha256:{sha256_hash(tar_bytes).hexdigest()}"

                gzip_buffer = BytesIO()
                with gzip.GzipFile(fileobj=gzip_buffer, mode="wb") as gz:
                    gz.write(tar_bytes)

                layer_blob = gzip_buffer.getvalue()
                layer_digest = f"sha256:{sha256_hash(layer_blob).hexdigest()}"

                config_blob = {
                    "architecture": platform.split("/")[1],
                    "config": {"Env": ["PATH=/usr/bin"], "Cmd": ["/bin/sh"]},
                    "rootfs": {"type": "layers", "diff_ids": [layer_diff_id]},
                    "history": [],
                }

                config_json = json_dumps(config_blob, separators=(",", ":"), sort_keys=True)
                config_digest = f"sha256:{sha256_hash(config_json.encode()).hexdigest()}"

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

                manifest_json = json_dumps(manifest, separators=(",", ":"), sort_keys=True)
                manifest_json_bytes = manifest_json.encode()

                return manifest, manifest_json_bytes, config_json, config_digest, layer_blob, layer_digest

            # Create manifests for both platforms
            _, amd64_manifest_bytes, amd64_config_json, amd64_config_digest, amd64_layer_blob, amd64_layer_digest = (
                _create_manifest_with_platform("linux/amd64")
            )
            amd64_manifest_digest = f"sha256:{sha256_hash(amd64_manifest_bytes).hexdigest()}"

            _, arm64_manifest_bytes, arm64_config_json, arm64_config_digest, arm64_layer_blob, arm64_layer_digest = (
                _create_manifest_with_platform("linux/arm64")
            )
            arm64_manifest_digest = f"sha256:{sha256_hash(arm64_manifest_bytes).hexdigest()}"

            # Create the registry index (what would come from registry)
            registry_index = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": amd64_manifest_digest,
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": arm64_manifest_digest,
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }

            # Create daemon exports for BOTH platforms
            def _create_daemon_export_tar(  # noqa: PLR0913
                manifest_bytes: bytes,
                manifest_digest: str,
                config_json: str,
                config_digest: str,
                layer_blob: bytes,
                layer_digest: str,
            ) -> str:
                """Create a valid OCI-archive tar for the platform."""
                export_tar_path = tmpdir / f"daemon_export_{manifest_digest.split(':')[1][:8]}.tar"

                with tar_open(str(export_tar_path), "w") as tar:
                    oci_layout = json_dumps({"imageLayoutVersion": "1.0.0"})
                    info = TarInfo(name="oci-layout")
                    info.size = len(oci_layout.encode())
                    tar.addfile(info, BytesIO(oci_layout.encode()))

                    index_json = {
                        "schemaVersion": 2,
                        "mediaType": "application/vnd.oci.image.index.v1+json",
                        "manifests": [
                            {
                                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                                "digest": manifest_digest,
                                "size": len(manifest_bytes),
                            }
                        ],
                    }
                    index_json_str = json_dumps(index_json)
                    info = TarInfo(name="index.json")
                    info.size = len(index_json_str.encode())
                    tar.addfile(info, BytesIO(index_json_str.encode()))

                    manifest_filename = manifest_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{manifest_filename}")
                    info.size = len(manifest_bytes)
                    tar.addfile(info, BytesIO(manifest_bytes))

                    config_bytes = config_json.encode()
                    config_filename = config_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{config_filename}")
                    info.size = len(config_bytes)
                    tar.addfile(info, BytesIO(config_bytes))

                    layer_filename = layer_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{layer_filename}")
                    info.size = len(layer_blob)
                    tar.addfile(info, BytesIO(layer_blob))

                return str(export_tar_path)

            amd64_daemon_tar = _create_daemon_export_tar(
                amd64_manifest_bytes,
                amd64_manifest_digest,
                amd64_config_json,
                amd64_config_digest,
                amd64_layer_blob,
                amd64_layer_digest,
            )
            arm64_daemon_tar = _create_daemon_export_tar(
                arm64_manifest_bytes,
                arm64_manifest_digest,
                arm64_config_json,
                arm64_config_digest,
                arm64_layer_blob,
                arm64_layer_digest,
            )

            # Mock OrasClient to track which digests are requested from registry
            mock_oras_client = Mock()
            downloaded_digests = []

            def mock_download_blob(_image_ref: str, digest: str, output_path: str) -> None:
                """Track registry downloads."""
                downloaded_digests.append(digest)
                if digest == amd64_manifest_digest:
                    Path(output_path).write_bytes(amd64_manifest_bytes)
                elif digest == arm64_manifest_digest:
                    Path(output_path).write_bytes(arm64_manifest_bytes)
                else:
                    Path(output_path).write_bytes(b"blob-data")

            mock_oras_client.download_blob = mock_download_blob
            mock_oras_client.get_manifest = Mock(return_value=registry_index)

            # Mock _resolve_all_platforms_from_manifest_list to return both exports
            def mock_resolve_all_platforms(_image_ref: str, _output_dir: str) -> dict[str, str | None]:
                return {
                    "linux/amd64": amd64_daemon_tar,
                    "linux/arm64": arm64_daemon_tar,
                }

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._resolve_all_platforms_from_manifest_list",
                side_effect=mock_resolve_all_platforms,
            ), patch("margot.services.package._verify_blob_digest"):
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    registry_index,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # ASSERTIONS: Both platforms should come from manifest list, zero registry downloads
            msg_amd64 = (
                f"amd64 digests should NOT be downloaded from registry (manifest-list resolved), "
                f"but {amd64_manifest_digest}, {amd64_config_digest}, {amd64_layer_digest} were checked"
            )
            assert amd64_manifest_digest not in downloaded_digests, msg_amd64
            assert amd64_config_digest not in downloaded_digests, msg_amd64
            assert amd64_layer_digest not in downloaded_digests, msg_amd64

            msg_arm64 = (
                f"arm64 digests should NOT be downloaded from registry (manifest-list resolved), "
                f"but {arm64_manifest_digest}, {arm64_config_digest}, {arm64_layer_digest} were checked"
            )
            assert arm64_manifest_digest not in downloaded_digests, msg_arm64
            assert arm64_config_digest not in downloaded_digests, msg_arm64
            assert arm64_layer_digest not in downloaded_digests, msg_arm64

            # No registry contact at all for this happy path
            assert len(downloaded_digests) == 0, (
                f"Expected zero registry downloads when both platforms in manifest list, "
                f"but {len(downloaded_digests)} digests were requested"
            )

            assert output_tar.exists(), f"Output tar should be created at {output_tar}"

    def test_manifest_list_one_platform_resolves_one_falls_through(self):  # noqa: PLR0915
        """One child digest from manifest list resolves locally, the other doesn't → mixed pull.

        Proves that unresolved platforms fall through to registry-based resolution.
        """
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            def _create_manifest_with_platform(
                platform: str,
            ) -> tuple[dict, bytes, str, str, bytes, str]:
                layer_tar_buffer = BytesIO()
                with tar_open(fileobj=layer_tar_buffer, mode="w") as tar:
                    file_content = f"layer content for {platform}".encode()
                    info = TarInfo(name=f"file-{platform}.txt")
                    info.size = len(file_content)
                    tar.addfile(tarinfo=info, fileobj=BytesIO(file_content))

                tar_bytes = layer_tar_buffer.getvalue()
                layer_diff_id = f"sha256:{sha256_hash(tar_bytes).hexdigest()}"

                gzip_buffer = BytesIO()
                with gzip.GzipFile(fileobj=gzip_buffer, mode="wb") as gz:
                    gz.write(tar_bytes)

                layer_blob = gzip_buffer.getvalue()
                layer_digest = f"sha256:{sha256_hash(layer_blob).hexdigest()}"

                config_blob = {
                    "architecture": platform.split("/")[1],
                    "config": {"Env": ["PATH=/usr/bin"], "Cmd": ["/bin/sh"]},
                    "rootfs": {"type": "layers", "diff_ids": [layer_diff_id]},
                    "history": [],
                }

                config_json = json_dumps(config_blob, separators=(",", ":"), sort_keys=True)
                config_digest = f"sha256:{sha256_hash(config_json.encode()).hexdigest()}"

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

                manifest_json = json_dumps(manifest, separators=(",", ":"), sort_keys=True)
                manifest_json_bytes = manifest_json.encode()

                return manifest, manifest_json_bytes, config_json, config_digest, layer_blob, layer_digest

            _, amd64_manifest_bytes, amd64_config_json, amd64_config_digest, amd64_layer_blob, amd64_layer_digest = (
                _create_manifest_with_platform("linux/amd64")
            )
            amd64_manifest_digest = f"sha256:{sha256_hash(amd64_manifest_bytes).hexdigest()}"

            _, arm64_manifest_bytes, _, arm64_config_digest, _, arm64_layer_digest = (
                _create_manifest_with_platform("linux/arm64")
            )
            arm64_manifest_digest = f"sha256:{sha256_hash(arm64_manifest_bytes).hexdigest()}"

            registry_index = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": amd64_manifest_digest,
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": arm64_manifest_digest,
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }

            def _create_daemon_export_tar(  # noqa: PLR0913
                manifest_bytes: bytes,
                manifest_digest: str,
                config_json: str,
                config_digest: str,
                layer_blob: bytes,
                layer_digest: str,
            ) -> str:
                export_tar_path = tmpdir / f"daemon_export_{manifest_digest.split(':')[1][:8]}.tar"
                with tar_open(str(export_tar_path), "w") as tar:
                    oci_layout = json_dumps({"imageLayoutVersion": "1.0.0"})
                    info = TarInfo(name="oci-layout")
                    info.size = len(oci_layout.encode())
                    tar.addfile(info, BytesIO(oci_layout.encode()))

                    index_json = {
                        "schemaVersion": 2,
                        "mediaType": "application/vnd.oci.image.index.v1+json",
                        "manifests": [
                            {
                                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                                "digest": manifest_digest,
                                "size": len(manifest_bytes),
                            }
                        ],
                    }
                    index_json_str = json_dumps(index_json)
                    info = TarInfo(name="index.json")
                    info.size = len(index_json_str.encode())
                    tar.addfile(info, BytesIO(index_json_str.encode()))

                    manifest_filename = manifest_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{manifest_filename}")
                    info.size = len(manifest_bytes)
                    tar.addfile(info, BytesIO(manifest_bytes))

                    config_bytes = config_json.encode()
                    config_filename = config_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{config_filename}")
                    info.size = len(config_bytes)
                    tar.addfile(info, BytesIO(config_bytes))

                    layer_filename = layer_digest.rsplit(":", maxsplit=1)[-1]
                    info = TarInfo(name=f"blobs/sha256/{layer_filename}")
                    info.size = len(layer_blob)
                    tar.addfile(info, BytesIO(layer_blob))

                return str(export_tar_path)

            amd64_daemon_tar = _create_daemon_export_tar(
                amd64_manifest_bytes,
                amd64_manifest_digest,
                amd64_config_json,
                amd64_config_digest,
                amd64_layer_blob,
                amd64_layer_digest,
            )

            mock_oras_client = Mock()
            downloaded_digests = []

            def mock_download_blob(_image_ref: str, digest: str, output_path: str) -> None:
                downloaded_digests.append(digest)
                if digest == amd64_manifest_digest:
                    Path(output_path).write_bytes(amd64_manifest_bytes)
                elif digest == arm64_manifest_digest:
                    Path(output_path).write_bytes(arm64_manifest_bytes)
                else:
                    Path(output_path).write_bytes(b"blob-data")

            mock_oras_client.download_blob = mock_download_blob
            mock_oras_client.get_manifest = Mock(return_value=registry_index)

            # Mock manifest list to return amd64 only (arm64 not resolved)
            def mock_resolve_all_platforms(_image_ref: str, _output_dir: str) -> dict[str, str | None]:
                return {
                    "linux/amd64": amd64_daemon_tar,
                    "linux/arm64": None,  # arm64 could not be resolved locally
                }

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._resolve_all_platforms_from_manifest_list",
                side_effect=mock_resolve_all_platforms,
            ), patch("margot.services.package._verify_blob_digest"):
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    registry_index,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # ASSERTIONS: amd64 from manifest list (no download), arm64 from registry (download all blobs)
            assert amd64_manifest_digest not in downloaded_digests, (
                f"amd64 manifest should NOT be downloaded (manifest-list resolved), "
                f"but {amd64_manifest_digest} was"
            )
            assert amd64_config_digest not in downloaded_digests, (
                f"amd64 config should NOT be downloaded (manifest-list resolved), "
                f"but {amd64_config_digest} was"
            )
            assert amd64_layer_digest not in downloaded_digests, (
                f"amd64 layer should NOT be downloaded (manifest-list resolved), "
                f"but {amd64_layer_digest} was"
            )

            # arm64 SHOULD be downloaded from registry
            assert arm64_manifest_digest in downloaded_digests, (
                f"arm64 manifest SHOULD be downloaded (not resolved locally), "
                f"but {arm64_manifest_digest} was NOT"
            )
            assert arm64_config_digest in downloaded_digests, (
                f"arm64 config SHOULD be downloaded (not resolved locally), "
                f"but {arm64_config_digest} was NOT"
            )
            assert arm64_layer_digest in downloaded_digests, (
                f"arm64 layer SHOULD be downloaded (not resolved locally), "
                f"but {arm64_layer_digest} was NOT"
            )

            assert output_tar.exists(), f"Output tar should be created at {output_tar}"

    def test_no_manifest_list_falls_back_to_existing_behavior(self):
        """When no local manifest list exists, behavior is unchanged.

        Proves that the new check doesn't affect normal registry-only case.
        """
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            # Create real manifests for both platforms
            def _create_manifest_with_platform(platform: str) -> tuple[bytes, str]:
                """Create a valid manifest and return (manifest_bytes, manifest_digest)."""
                config_blob = {
                    "architecture": platform.split("/")[1],
                    "config": {"Env": ["PATH=/usr/bin"], "Cmd": ["/bin/sh"]},
                    "rootfs": {"type": "layers", "diff_ids": []},
                    "history": [],
                }
                config_json = json_dumps(config_blob, separators=(",", ":"), sort_keys=True)
                config_digest = f"sha256:{sha256_hash(config_json.encode()).hexdigest()}"

                manifest = {
                    "schemaVersion": 2,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {
                        "size": len(config_json.encode()),
                        "digest": config_digest,
                        "mediaType": "application/vnd.oci.image.config.v1+json",
                    },
                    "layers": [],
                }

                manifest_json = json_dumps(manifest, separators=(",", ":"), sort_keys=True)
                manifest_json_bytes = manifest_json.encode()
                manifest_digest = f"sha256:{sha256_hash(manifest_json_bytes).hexdigest()}"

                return manifest_json_bytes, manifest_digest

            amd64_manifest_bytes, amd64_manifest_digest = _create_manifest_with_platform("linux/amd64")
            arm64_manifest_bytes, arm64_manifest_digest = _create_manifest_with_platform("linux/arm64")

            # Simple two-platform index
            manifest_index = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": amd64_manifest_digest,
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": arm64_manifest_digest,
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }

            mock_oras_client = Mock()
            downloaded_digests = []

            def mock_download_blob(_image_ref: str, digest: str, output_path: str) -> None:
                downloaded_digests.append(digest)
                if digest == amd64_manifest_digest:
                    Path(output_path).write_bytes(amd64_manifest_bytes)
                elif digest == arm64_manifest_digest:
                    Path(output_path).write_bytes(arm64_manifest_bytes)
                else:
                    Path(output_path).write_bytes(b"{}")  # Generic JSON blob

            mock_oras_client.download_blob = mock_download_blob
            mock_oras_client.get_manifest = Mock(return_value=manifest_index)

            # Mock manifest list to return empty (no local manifest list)
            def mock_resolve_all_platforms(_image_ref: str, _output_dir: str) -> dict[str, str | None]:
                return {}  # Empty = no manifest list found

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._resolve_all_platforms_from_manifest_list",
                side_effect=mock_resolve_all_platforms,
            ), patch(
                "margot.services.package._try_daemon_match_for_platform", return_value=None
            ), patch(
                "margot.services.package._verify_blob_digest"
            ):
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    manifest_index,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # Behavior is unchanged: both platforms should be attempted from registry
            # (exact digests don't matter for this regression test)
            assert len(downloaded_digests) > 0, (
                "When no manifest list exists, registry fallback should be used (downloads expected)"
            )
            assert output_tar.exists(), f"Output tar should be created at {output_tar}"



class TestManifestListResolutionInAutoMode:
    """Tests for local Podman manifest list resolution in auto mode."""

    def test_manifest_list_checked_before_per_platform_daemon_lookup(self):
        """Verify _resolve_all_platforms_from_manifest_list is called before per-platform lookups."""
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            target_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "digest": "sha256:amd64",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "digest": "sha256:arm64",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            }

            mock_oras_client = Mock()

            call_order = []

            # Mock manifest list resolution
            def mock_resolve_all_platforms(_ref: str, _export_dir: str) -> dict[str, str | None]:
                call_order.append("manifest_list")
                return {"linux/amd64": "/tmp/export.tar", "linux/arm64": None}

            # Mock per-platform daemon lookup
            def mock_try_daemon(_ref: str, _platform: str, _platform_desc: Any, _export_dir: Any) -> str | None:
                call_order.append(f"daemon_lookup_{_platform}")
                return None

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._resolve_all_platforms_from_manifest_list",
                side_effect=mock_resolve_all_platforms,
            ), patch(
                "margot.services.package._try_daemon_match_for_platform",
                side_effect=mock_try_daemon,
            ), patch(
                "margot.services.package._extract_blobs_from_daemon_tar"
            ), patch(
                "margot.services.package._create_oci_image_layout_tar"
            ):
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    target_manifest,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # VERIFY: manifest_list called BEFORE any per-platform daemon lookups
            assert "manifest_list" in call_order, "Manifest list should be checked"
            assert call_order[0] == "manifest_list", (
                f"Manifest list should be checked first, but call order was: {call_order}"
            )

    def test_manifest_list_both_platforms_resolved_skips_per_platform_lookup(self):
        """When both platforms from manifest list, per-platform daemon lookup should be skipped."""
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            target_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {"digest": "sha256:amd64", "platform": {"os": "linux", "architecture": "amd64"}},
                    {"digest": "sha256:arm64", "platform": {"os": "linux", "architecture": "arm64"}},
                ],
            }

            mock_oras_client = Mock()
            per_platform_lookup_calls = []

            # Mock manifest list to return both platforms
            def mock_resolve_all_platforms(_ref: str, _export_dir: str) -> dict[str, str | None]:
                return {
                    "linux/amd64": "/tmp/amd64.tar",
                    "linux/arm64": "/tmp/arm64.tar",
                }

            # Track per-platform lookups
            def mock_try_daemon(ref: str, platform: str, _platform_desc: Any, _export_dir: Any) -> str | None:
                per_platform_lookup_calls.append((ref, platform))
                return None

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._resolve_all_platforms_from_manifest_list",
                side_effect=mock_resolve_all_platforms,
            ), patch(
                "margot.services.package._try_daemon_match_for_platform",
                side_effect=mock_try_daemon,
            ), patch(
                "margot.services.package._extract_blobs_from_daemon_tar"
            ), patch(
                "margot.services.package._create_oci_image_layout_tar"
            ):
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    target_manifest,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # VERIFY: per-platform daemon lookups should be skipped (both platforms resolved via manifest list)
            assert len(per_platform_lookup_calls) == 0, (
                f"Per-platform daemon lookups should be skipped when manifest list provides all platforms, "
                f"but got {per_platform_lookup_calls}"
            )

    def test_manifest_list_partial_resolution_then_per_platform_fallback(self):
        """When manifest list provides one platform, per-platform daemon lookup for other."""
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            target_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {"digest": "sha256:amd64", "platform": {"os": "linux", "architecture": "amd64"}},
                    {"digest": "sha256:arm64", "platform": {"os": "linux", "architecture": "arm64"}},
                ],
            }

            mock_oras_client = Mock()
            per_platform_lookup_calls = []

            # Mock manifest list to return only amd64
            def mock_resolve_all_platforms(_ref: str, _export_dir: str) -> dict[str, str | None]:
                return {
                    "linux/amd64": "/tmp/amd64.tar",
                    "linux/arm64": None,  # Not available locally
                }

            # Track which platforms go through per-platform lookup
            def mock_try_daemon(_ref: str, platform: str, _platform_desc: Any, _export_dir: Any) -> str | None:
                per_platform_lookup_calls.append(platform)
                return None

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._resolve_all_platforms_from_manifest_list",
                side_effect=mock_resolve_all_platforms,
            ), patch(
                "margot.services.package._try_daemon_match_for_platform",
                side_effect=mock_try_daemon,
            ), patch(
                "margot.services.package._extract_blobs_from_daemon_tar"
            ), patch(
                "margot.services.package._create_oci_image_layout_tar"
            ):
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    target_manifest,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # VERIFY: only arm64 (unresolved) goes through per-platform lookup
            assert "linux/amd64" not in per_platform_lookup_calls, (
                "amd64 should come from manifest list, not per-platform lookup"
            )
            assert "linux/arm64" in per_platform_lookup_calls, (
                "arm64 should be looked up per-platform (not in manifest list)"
            )

    def test_manifest_list_exception_handled_gracefully(self):
        """If manifest list lookup fails, should return empty dict (fallback to registry)."""
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            target_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {"digest": "sha256:amd64", "platform": {"os": "linux", "architecture": "amd64"}},
                ],
            }

            mock_oras_client = Mock()
            per_platform_lookup_calls = []

            # Mock manifest list to return empty (simulates exception handling inside the function)
            def mock_resolve_returns_empty(_ref: str, _export_dir: str) -> dict[str, str | None]:
                return {}  # Empty dict simulates exception handling in the real function

            # Track per-platform lookups
            def mock_try_daemon(_ref: str, platform: str, _platform_desc: Any, _export_dir: Any) -> str | None:
                per_platform_lookup_calls.append(platform)
                return None

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._resolve_all_platforms_from_manifest_list",
                side_effect=mock_resolve_returns_empty,
            ), patch(
                "margot.services.package._try_daemon_match_for_platform",
                side_effect=mock_try_daemon,
            ), patch(
                "margot.services.package._create_oci_image_layout_tar"
            ):
                # Should NOT raise; should fall back to per-platform lookups
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    target_manifest,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # VERIFY: All platforms go through per-platform lookup (manifest list returned empty)
            assert "linux/amd64" in per_platform_lookup_calls, (
                "When manifest list fails/returns empty, all platforms should try per-platform daemon lookup"
            )

    def test_no_manifest_list_returns_empty_dict(self):
        """When no manifest list exists, should return empty dict (no local resolution)."""
        with TemporaryDirectory() as _tmpdir_str:
            tmpdir = Path(_tmpdir_str)

            target_manifest = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {"digest": "sha256:amd64", "platform": {"os": "linux", "architecture": "amd64"}},
                ],
            }

            mock_oras_client = Mock()
            per_platform_lookup_calls = []

            # Mock manifest list to return empty (no manifest list found)
            def mock_resolve_empty(_ref: str, _export_dir: str) -> dict[str, str | None]:
                return {}

            # Track per-platform lookups
            def mock_try_daemon(_ref: str, platform: str, _platform_desc: Any, _export_dir: Any) -> str | None:
                per_platform_lookup_calls.append(platform)
                return None

            output_tar = tmpdir / "output.oci.tar"

            with patch(
                "margot.services.package._resolve_all_platforms_from_manifest_list",
                side_effect=mock_resolve_empty,
            ), patch(
                "margot.services.package._try_daemon_match_for_platform",
                side_effect=mock_try_daemon,
            ), patch(
                "margot.services.package._create_oci_image_layout_tar"
            ):
                package_service._pull_image_with_local_daemon_optimization(
                    "test:latest",
                    target_manifest,
                    mock_oras_client,
                    str(output_tar),
                    str(tmpdir / "daemon_dir"),
                )

            # VERIFY: All platforms go through per-platform lookup (no manifest list)
            assert "linux/amd64" in per_platform_lookup_calls, (
                "When no manifest list exists, all platforms should try per-platform daemon lookup"
            )
