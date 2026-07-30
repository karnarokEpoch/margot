"""Unit tests for infra/oci.py push methods."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from margot.infra.oci import OrasClient


class TestPushMargo:
    """Tests for OrasClient.push_margo()."""

    def test_push_margo_calls_client_push_with_correct_args(self, mocker: Any, tmp_path: Path) -> None:
        """Should call _push_artifact with correct target, artifact_type, file_entries, manifest_annotations."""
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

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
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

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
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

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
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

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
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

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
