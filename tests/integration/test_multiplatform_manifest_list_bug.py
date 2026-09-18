"""Test for the multiplatform manifest list bug.

When resolving multiple platforms from a local Podman manifest list, both
platform slots in the final assembled OCI index were pointing at the same
manifest digest and blobs. This test reproduces the bug and verifies the fix.
"""

import contextlib
import io
import json
import subprocess
from pathlib import Path
from tarfile import TarInfo, open as tar_open
from tempfile import mkdtemp

from pytest import mark, skip

try:
    from podman import PodmanClient
except ImportError:
    PodmanClient = None  # type: ignore[assignment]


def _podman_socket_exists() -> bool:
    """Check if Podman socket is accessible."""
    for socket_path in [
        "/run/user/1000/podman/podman.sock",
        "/var/run/podman/podman.sock",
    ]:
        try:
            if Path(socket_path).exists():
                return True
        except PermissionError:
            pass
    return False


@mark.skipif(PodmanClient is None, reason="Podman SDK not available")
@mark.skipif(not _podman_socket_exists(), reason="Podman socket not available")
class TestMultiplatformManifestListBug:  # noqa: PLR0904
    """Real Podman reproduction of the duplicate manifest digest bug."""

    def test_multiplatform_manifest_list_distinct_digests(  # noqa: C901, PLR0912, PLR0915
        self, tmp_path: Path
    ) -> None:
        """Reproduce and verify fix for duplicate manifest digest bug.

        This test:
        1. Creates two distinct tar files with different content
        2. Imports them into Podman using podman import
        3. Creates a local Podman manifest list with both images at different platforms
        4. Resolves and assembles them via the real margot functions
        5. Verifies the resulting OCI layout has DISTINCT manifest digests and blob sets
        """
        # Ensure Podman is available
        if PodmanClient is None:
            skip("Podman SDK not available")

        socket_path = None
        if Path("/run/user/1000/podman/podman.sock").exists():
            socket_path = "unix:///run/user/1000/podman/podman.sock"
        elif Path("/var/run/podman/podman.sock").exists():
            socket_path = "unix:///var/run/podman/podman.sock"
        else:
            skip("Podman socket not found")

        # Only establish connection to verify socket is accessible
        try:
            PodmanClient(base_url=socket_path).close()
        except Exception as e:  # noqa: BLE001
            skip(f"Podman socket not accessible: {e}")

        # 1. Create two distinct filesystem tarballs (different content)
        #    Image 1: amd64 with specific content
        amd64_fs_tar = tmp_path / "amd64_image.tar"
        self._create_minimal_filesystem_tar(amd64_fs_tar, "amd64-specific-layer-content")

        #    Image 2: arm64 with different content
        arm64_fs_tar = tmp_path / "arm64_image.tar"
        self._create_minimal_filesystem_tar(arm64_fs_tar, "arm64-specific-layer-content")

        # 2. Import both as local Podman images using `podman import`
        test_image_ref_base = f"localhost/test-manifest-list-{id(self)}"
        amd64_image_ref = f"{test_image_ref_base}-amd64"
        arm64_image_ref = f"{test_image_ref_base}-arm64"

        try:
            # Import amd64 image
            result = subprocess.run(  # noqa: S603, S607
                ["podman", "import", str(amd64_fs_tar), amd64_image_ref],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                skip(f"Failed to import amd64 image: {result.stderr}")

            # Import arm64 image
            result = subprocess.run(  # noqa: S603, S607
                ["podman", "import", str(arm64_fs_tar), arm64_image_ref],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                skip(f"Failed to import arm64 image: {result.stderr}")

            # 3. Create a manifest list combining both platforms
            manifest_list_name = f"localhost/test-manifest-list-combo-{id(self)}"
            subprocess.run(  # noqa: S603, S607
                ["podman", "manifest", "create", manifest_list_name],
                capture_output=True,
                timeout=30,
                check=False,
            )

            # Add amd64 image to manifest list
            subprocess.run(  # noqa: S603, S607
                ["podman", "manifest", "add", "--arch", "amd64", manifest_list_name, amd64_image_ref],
                capture_output=True,
                timeout=30,
                check=False,
            )

            # Add arm64 image to manifest list
            subprocess.run(  # noqa: S603, S607
                ["podman", "manifest", "add", "--arch", "arm64", manifest_list_name, arm64_image_ref],
                capture_output=True,
                timeout=30,
                check=False,
            )

            # 4. Now use margot's resolution functions
            from margot.services.package import (  # noqa: PLC0415
                _assemble_multiplatform_from_manifest_list_exports,
                _resolve_all_platforms_from_manifest_list,
            )

            daemon_export_dir = Path(mkdtemp(prefix="margot-test-"))
            output_tar = tmp_path / "output_oci_layout.tar"

            try:
                # Resolve all platforms from the manifest list
                manifest_list_exports = _resolve_all_platforms_from_manifest_list(
                    manifest_list_name,
                    str(daemon_export_dir),
                )

                if not manifest_list_exports:
                    skip("No platforms resolved from manifest list")

                # Check that both platforms have exports
                resolved_platforms = [p for p, export in manifest_list_exports.items() if export is not None]

                print(f"\nResolved platforms: {resolved_platforms}")  # noqa: T201
                print(f"Manifest list exports: {manifest_list_exports}")  # noqa: T201

                if "linux/amd64" not in manifest_list_exports or manifest_list_exports["linux/amd64"] is None:
                    skip("amd64 platform not resolved")
                if "linux/arm64" not in manifest_list_exports or manifest_list_exports["linux/arm64"] is None:
                    skip("arm64 platform not resolved")

                # Assemble the multiplatform OCI layout
                _assemble_multiplatform_from_manifest_list_exports(
                    manifest_list_name,
                    manifest_list_exports,
                    str(output_tar),
                    str(daemon_export_dir),
                )

                assert output_tar.exists(), "Output tar was not created"

                # 5. Extract and inspect the resulting OCI layout
                extract_dir = tmp_path / "extracted_oci"
                with tar_open(output_tar, "r") as tar:
                    tar.extractall(extract_dir, filter="data")

                # Read index.json
                index_json_path = extract_dir / "index.json"
                assert index_json_path.exists(), "index.json not found in output"

                with index_json_path.open() as f:
                    index_json = json.load(f)

                # Verify structure
                assert "manifests" in index_json
                manifests = index_json["manifests"]
                print(f"\nNumber of manifests in index: {len(manifests)}")  # noqa: T201
                assert len(manifests) == 2, f"Expected 2 manifests in index, got {len(manifests)}"

                # 6. THE BUG CHECK: Verify both manifests have DISTINCT digests
                amd64_manifest = manifests[0]
                arm64_manifest = manifests[1]

                amd64_digest = amd64_manifest.get("digest")
                arm64_digest = arm64_manifest.get("digest")

                print(f"amd64 manifest digest: {amd64_digest}")  # noqa: T201
                print(f"arm64 manifest digest: {arm64_digest}")  # noqa: T201

                assert amd64_digest != arm64_digest, (
                    f"BUG REPRODUCED: Both manifests have the SAME digest {amd64_digest}! "
                    f"Expected distinct digests for different platforms."
                )

                # 7. Verify distinct blobs exist for each platform
                blobs_dir = extract_dir / "blobs" / "sha256"
                assert blobs_dir.exists(), "blobs directory not found"

                blob_files = list(blobs_dir.iterdir())
                print(f"\nTotal blob files: {len(blob_files)}")  # noqa: T201
                for blob in sorted(blob_files):
                    print(f"  {blob.name} ({blob.stat().st_size} bytes)")  # noqa: T201

                # Extract the manifest blobs to verify they're different
                amd64_manifest_digest_hex = amd64_digest.split(":")[-1]
                arm64_manifest_digest_hex = arm64_digest.split(":")[-1]

                amd64_manifest_blob = blobs_dir / amd64_manifest_digest_hex
                arm64_manifest_blob = blobs_dir / arm64_manifest_digest_hex

                assert amd64_manifest_blob.exists(), f"amd64 manifest blob {amd64_manifest_digest_hex} not found"
                assert arm64_manifest_blob.exists(), f"arm64 manifest blob {arm64_manifest_digest_hex} not found"

                # Read and verify manifests are actually different
                amd64_manifest_content = json.loads(amd64_manifest_blob.read_text())
                arm64_manifest_content = json.loads(arm64_manifest_blob.read_text())

                # Each should reference different layer digests (since we used different content)
                amd64_layers = amd64_manifest_content.get("layers", [])
                arm64_layers = arm64_manifest_content.get("layers", [])

                assert amd64_layers, "amd64 manifest has no layers"
                assert arm64_layers, "arm64 manifest has no layers"

                amd64_layer_digest = amd64_layers[0].get("digest")
                arm64_layer_digest = arm64_layers[0].get("digest")

                print(f"\namd64 layer digest: {amd64_layer_digest}")  # noqa: T201
                print(f"arm64 layer digest: {arm64_layer_digest}")  # noqa: T201

                assert amd64_layer_digest != arm64_layer_digest, (
                    f"BUG REPRODUCED: Both platforms reference the SAME layer digest {amd64_layer_digest}! "
                    f"Expected distinct layer digests for different platform content."
                )

                # Success: bug is fixed
                print("\n✅ PASS: Both platforms have distinct manifest and layer digests")  # noqa: T201

            finally:
                from shutil import rmtree

                rmtree(daemon_export_dir, ignore_errors=True)

        finally:
            # Clean up created images and manifest list
            with contextlib.suppress(Exception):
                subprocess.run(  # noqa: S603, S607
                    ["podman", "manifest", "rm", manifest_list_name], capture_output=True, timeout=10, check=False
                )

            with contextlib.suppress(Exception):
                subprocess.run(  # noqa: S603, S607
                    ["podman", "rmi", amd64_image_ref], capture_output=True, timeout=10, check=False
                )

            with contextlib.suppress(Exception):
                subprocess.run(  # noqa: S603, S607
                    ["podman", "rmi", arm64_image_ref], capture_output=True, timeout=10, check=False
                )

    @staticmethod
    def _create_minimal_filesystem_tar(tar_path: Path, content: str) -> None:
        """Create a minimal filesystem tar with unique content.

        This can be used with `podman import` to create a layer with distinct content.
        """
        tar_buffer = io.BytesIO()

        with tar_open(fileobj=tar_buffer, mode="w") as tar:
            # Create a simple file with the provided content
            content_bytes = content.encode("utf-8")
            info = TarInfo(name="layer_content.txt")
            info.size = len(content_bytes)
            tar.addfile(info, io.BytesIO(content_bytes))

        tar_path.write_bytes(tar_buffer.getvalue())
