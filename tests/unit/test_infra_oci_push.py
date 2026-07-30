"""Unit tests for infra/oci.py push methods."""

from contextlib import suppress
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from margot.infra.oci import OrasClient


class TestPushMargo:
    """Tests for OrasClient.push_margo()."""

    def test_push_margo_calls_client_push_with_correct_args(self, mocker: Any, tmp_path: Path) -> None:
        """Should call _push_artifact with correct target, artifact_type, file_entries, manifest_annotations."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)

        # Create build dir structure
        margo_dir = tmp_path / "1.0.0" / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("name: test\n")

        client = OrasClient()
        mocker.patch.object(client, "_push_artifact")

        client.push_margo(
            build_dir=str(tmp_path),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        client._push_artifact.assert_called_once_with(
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            artifact_type="application/vnd.margo.app.v1+json",
            file_entries=[
                (margo_dir / "app.yaml", "application/vnd.margo.app.description.v1+yaml", "app.yaml"),
            ],
            manifest_annotations={
                "org.opencontainers.image.title": "testapp",
                "org.opencontainers.image.description": "Test application",
            },
        )

    def test_push_margo_includes_optional_files_when_present(self, mocker: Any, tmp_path: Path) -> None:
        """Should include optional resource files when they exist on disk."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)

        # Create build dir with optional files
        margo_dir = tmp_path / "1.0.0" / "margo"
        resources_dir = margo_dir / "resources"
        resources_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("name: test\n")
        (resources_dir / "icon.png").write_bytes(b"\x89PNG")
        (resources_dir / "license.txt").write_text("MIT")

        client = OrasClient()
        mocker.patch.object(client, "_push_artifact")

        client.push_margo(
            build_dir=str(tmp_path),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        call_args = client._push_artifact.call_args
        file_entries = call_args[1]["file_entries"]
        assert len(file_entries) == 3
        assert (margo_dir / "app.yaml", "application/vnd.margo.app.description.v1+yaml", "app.yaml") in file_entries
        assert (resources_dir / "icon.png", "application/vnd.margo.app.icon.v1+png", "resources/icon.png") in file_entries
        assert (
            resources_dir / "license.txt",
            "application/vnd.margo.app.license.v1+plain",
            "resources/license.txt",
        ) in file_entries

    def test_push_margo_skips_missing_optional_files(self, mocker: Any, tmp_path: Path) -> None:
        """Should skip optional files that don't exist on disk."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)

        # Create build dir with only required file
        margo_dir = tmp_path / "1.0.0" / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("name: test\n")

        client = OrasClient()
        mocker.patch.object(client, "_push_artifact")

        client.push_margo(
            build_dir=str(tmp_path),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        call_args = client._push_artifact.call_args
        file_entries = call_args[1]["file_entries"]
        assert len(file_entries) == 1
        assert file_entries[0] == (margo_dir / "app.yaml", "application/vnd.margo.app.description.v1+yaml", "app.yaml")


class TestPushCompose:
    """Tests for OrasClient.push_compose()."""

    def test_push_compose_calls_client_push_with_correct_args(self, mocker: Any) -> None:
        """Should call _push_artifact with correct target, artifact_type, file_entries, manifest_annotations."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)

        client = OrasClient()
        mocker.patch.object(client, "_push_artifact")

        client.push_compose(
            archive_path="/build/1.0.0/testapp-1.0.0.tgz",
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        client._push_artifact.assert_called_once_with(
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            artifact_type="application/vnd.org.margo.component.compose+json",
            file_entries=[
                (
                    Path("/build/1.0.0/testapp-1.0.0.tgz"),
                    "application/vnd.org.margo.component.compose.tar+gzip",
                    "testapp-1.0.0.tgz",
                ),
            ],
            manifest_annotations={
                "org.margo.component.type": "compose",
                "org.margo.component.version": "1.0.0",
                "org.opencontainers.image.title": "testapp",
                "org.opencontainers.image.description": "Test application",
            },
        )


class TestPushQuadlet:
    """Tests for OrasClient.push_quadlet()."""

    def test_push_quadlet_calls_client_push_with_correct_args(self, mocker: Any) -> None:
        """Should call _push_artifact with correct target, artifact_type, file_entries, manifest_annotations."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)

        client = OrasClient()
        mocker.patch.object(client, "_push_artifact")

        client.push_quadlet(
            archive_path="/build/1.0.0/testapp-1.0.0.tgz",
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        client._push_artifact.assert_called_once_with(
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            artifact_type="application/vnd.org.margo.component.quadlet+json",
            file_entries=[
                (
                    Path("/build/1.0.0/testapp-1.0.0.tgz"),
                    "application/vnd.org.margo.component.quadlet.tar+gzip",
                    "testapp-1.0.0.tgz",
                ),
            ],
            manifest_annotations={
                "org.margo.component.type": "quadlet",
                "org.margo.component.version": "1.0.0",
                "org.opencontainers.image.title": "testapp",
                "org.opencontainers.image.description": "Test application",
            },
        )


class TestPushArtifact:
    """Tests for OrasClient._push_artifact() internals (lines 255-299)."""

    def _setup_mocks(self, mocker: Any) -> dict[str, Any]:
        """Common mock setup for _push_artifact tests."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)

        container_mock = MagicMock()
        get_container = mocker.patch.object(OrasClient, "get_container", return_value=container_mock)

        # Mock auth.load_configs on the instance (accessed via self.auth)
        auth_mock = MagicMock()
        mocker.patch.object(OrasClient, "auth", new_callable=lambda: property(lambda _self: auth_mock), create=True)

        upload_blob = mocker.patch.object(OrasClient, "upload_blob", return_value=MagicMock(status_code=200))
        check_200 = mocker.patch.object(OrasClient, "_check_200_response")
        upload_manifest = mocker.patch.object(OrasClient, "upload_manifest", return_value=MagicMock(status_code=201))

        mocker.patch(
            "margot.infra.oci.oras.oci.NewManifest",
            return_value={
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {},
                "layers": [],
                "annotations": {},
            },
        )
        mocker.patch(
            "margot.infra.oci.oras.oci.NewLayer",
            return_value={"mediaType": "...", "size": 10, "digest": "sha256:abc", "annotations": {}},
        )
        mocker.patch(
            "margot.infra.oci.oras.oci.ManifestConfig",
            return_value=(
                {
                    "mediaType": "application/vnd.oci.empty.v1+json",
                    "size": 2,
                    "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                },
                None,
            ),
        )

        return {
            "container_mock": container_mock,
            "auth_mock": auth_mock,
            "get_container": get_container,
            "upload_blob": upload_blob,
            "check_200": check_200,
            "upload_manifest": upload_manifest,
        }

    def test_push_artifact_uploads_each_layer(self, mocker: Any, tmp_path: Path) -> None:
        """Should call upload_blob once per layer + once for config = 3 total for 2 files."""
        mocks = self._setup_mocks(mocker)

        # Create two real files as layer entries
        file1 = tmp_path / "layer1.yaml"
        file1.write_text("content1")
        file2 = tmp_path / "layer2.yaml"
        file2.write_text("content2")

        client = OrasClient()
        client._push_artifact(
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            artifact_type="application/vnd.margo.app.v1+json",
            file_entries=[
                (file1, "application/vnd.margo.app.description.v1+yaml", "layer1.yaml"),
                (file2, "application/vnd.margo.app.description.v1+yaml", "layer2.yaml"),
            ],
            manifest_annotations={"org.opencontainers.image.title": "testapp"},
        )

        # 2 layer blobs + 1 config blob = 3 upload_blob calls
        assert mocks["upload_blob"].call_count == 3

    def test_push_artifact_uploads_manifest_with_artifact_type(self, mocker: Any, tmp_path: Path) -> None:
        """Should upload manifest with correct artifactType."""
        mocks = self._setup_mocks(mocker)

        file1 = tmp_path / "layer.yaml"
        file1.write_text("content")

        client = OrasClient()
        client._push_artifact(
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            artifact_type="application/vnd.margo.app.v1+json",
            file_entries=[(file1, "application/vnd.margo.app.description.v1+yaml", "layer.yaml")],
            manifest_annotations={"org.opencontainers.image.title": "testapp"},
        )

        mocks["upload_manifest"].assert_called_once()
        call_kwargs = mocks["upload_manifest"].call_args[1]
        manifest = call_kwargs["manifest"]
        assert manifest["artifactType"] == "application/vnd.margo.app.v1+json"

    def test_push_artifact_manifest_annotations_include_created(self, mocker: Any, tmp_path: Path) -> None:
        """Should include org.opencontainers.image.created in manifest annotations."""
        mocks = self._setup_mocks(mocker)

        file1 = tmp_path / "layer.yaml"
        file1.write_text("content")

        client = OrasClient()
        client._push_artifact(
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            artifact_type="application/vnd.margo.app.v1+json",
            file_entries=[(file1, "application/vnd.margo.app.description.v1+yaml", "layer.yaml")],
            manifest_annotations={"org.opencontainers.image.title": "testapp"},
        )

        call_kwargs = mocks["upload_manifest"].call_args[1]
        manifest = call_kwargs["manifest"]
        assert "org.opencontainers.image.created" in manifest["annotations"]

    def test_push_artifact_tempfile_cleaned_up(self, mocker: Any, tmp_path: Path) -> None:
        """Should clean up the temp config file after successful push."""
        mocks = self._setup_mocks(mocker)

        file1 = tmp_path / "layer.yaml"
        file1.write_text("content")

        # Track the config temp file path (has .json suffix)
        created_temps: list[Path] = []

        def track_blob_upload(*args: Any, **kwargs: Any) -> MagicMock:
            blob_path = kwargs.get("blob") or (args[0] if args else None)
            if blob_path and str(blob_path).endswith(".json"):
                created_temps.append(Path(blob_path))
            return MagicMock(status_code=200)

        mocks["upload_blob"].side_effect = track_blob_upload

        client = OrasClient()
        client._push_artifact(
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            artifact_type="application/vnd.margo.app.v1+json",
            file_entries=[(file1, "application/vnd.margo.app.description.v1+yaml", "layer.yaml")],
            manifest_annotations={"org.opencontainers.image.title": "testapp"},
        )

        # The temp config file should have been cleaned up
        assert len(created_temps) == 1
        assert not created_temps[0].exists()

    def test_push_artifact_tempfile_cleaned_up_on_upload_error(self, mocker: Any, tmp_path: Path) -> None:
        """Should clean up temp config file even when upload_blob raises on config."""
        mocks = self._setup_mocks(mocker)

        file1 = tmp_path / "layer.yaml"
        file1.write_text("content")

        # First call (layer upload) succeeds, second call (config upload) raises
        call_count = {"n": 0}
        created_temps: list[Path] = []

        def failing_upload(*args: Any, **kwargs: Any) -> MagicMock:
            call_count["n"] += 1
            blob_path = kwargs.get("blob") or (args[0] if args else None)
            if blob_path and str(blob_path).endswith(".json"):
                created_temps.append(Path(blob_path))
            if call_count["n"] == 2:
                raise RuntimeError("upload failed")
            return MagicMock(status_code=200)

        mocks["upload_blob"].side_effect = failing_upload

        client = OrasClient()
        with suppress(RuntimeError):
            client._push_artifact(
                target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
                artifact_type="application/vnd.margo.app.v1+json",
                file_entries=[(file1, "application/vnd.margo.app.description.v1+yaml", "layer.yaml")],
                manifest_annotations={"org.opencontainers.image.title": "testapp"},
            )

        # The temp file should have been cleaned up despite the error
        assert len(created_temps) == 1
        assert not created_temps[0].exists()
