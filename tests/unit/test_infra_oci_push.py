"""Unit tests for infra/oci.py push methods."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from margot.infra.oci import OrasClient


class TestPushMargo:
    """Tests for OrasClient.push_margo()."""

    def test_push_margo_calls_client_push_with_correct_args(self, mocker: Any, tmp_path: Path) -> None:
        """Should call _client.push with correct files, target, manifest_config, manifest_annotations."""
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

        # Create build dir structure
        margo_dir = tmp_path / "1.0.0" / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("name: test\n")

        client = OrasClient()
        client.push_margo(
            build_dir=str(tmp_path),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        mock_lib.push.assert_called_once_with(
            files=[(str(margo_dir / "app.yaml"), "application/vnd.margo.app.description.v1+yaml")],
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            manifest_config={"mediaType": "application/vnd.margo.app.v1+json"},
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
        client.push_margo(
            build_dir=str(tmp_path),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        call_args = mock_lib.push.call_args
        files = call_args[1]["files"]
        assert len(files) == 3
        assert (str(margo_dir / "app.yaml"), "application/vnd.margo.app.description.v1+yaml") in files
        assert (str(resources_dir / "icon.png"), "image/png") in files
        assert (str(resources_dir / "license.txt"), "text/plain") in files

    def test_push_margo_skips_missing_optional_files(self, mocker: Any, tmp_path: Path) -> None:
        """Should skip optional files that don't exist on disk."""
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

        # Create build dir with only required file
        margo_dir = tmp_path / "1.0.0" / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("name: test\n")

        client = OrasClient()
        client.push_margo(
            build_dir=str(tmp_path),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        call_args = mock_lib.push.call_args
        files = call_args[1]["files"]
        assert len(files) == 1
        assert files[0] == (str(margo_dir / "app.yaml"), "application/vnd.margo.app.description.v1+yaml")


class TestPushCompose:
    """Tests for OrasClient.push_compose()."""

    def test_push_compose_calls_client_push_with_correct_args(self, mocker: Any) -> None:
        """Should call _client.push with correct files, target, manifest_config, manifest_annotations."""
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

        client = OrasClient()
        client.push_compose(
            archive_path="/build/1.0.0/testapp-1.0.0.tgz",
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        mock_lib.push.assert_called_once_with(
            files=[("/build/1.0.0/testapp-1.0.0.tgz", "application/vnd.org.margo.component.compose.tar+gzip")],
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            manifest_config={"mediaType": "application/vnd.org.margo.component.compose+json"},
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
        """Should call _client.push with correct files, target, manifest_config, manifest_annotations."""
        mock_lib = MagicMock()
        mocker.patch("margot.infra.oci.OrasClientLib", return_value=mock_lib)

        client = OrasClient()
        client.push_quadlet(
            archive_path="/build/1.0.0/testapp-1.0.0.tgz",
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo",
            name="testapp",
            description="Test application",
        )

        mock_lib.push.assert_called_once_with(
            files=[("/build/1.0.0/testapp-1.0.0.tgz", "application/vnd.org.margo.component.quadlet+json")],
            target="public.ecr.aws/g2n4p2m7/margo:1.0.0",
            manifest_config={"mediaType": "application/vnd.org.margo.component.quadlet+json"},
            manifest_annotations={
                "org.margo.component.type": "quadlet",
                "org.margo.component.version": "1.0.0",
                "org.opencontainers.image.title": "testapp",
                "org.opencontainers.image.description": "Test application",
            },
        )
