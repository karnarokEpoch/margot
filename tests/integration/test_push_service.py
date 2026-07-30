"""Integration tests for services/push.py."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pytest import fixture, raises

from margot.domain.models import PackageType
from margot.infra.credentials import CredentialsExpiredError
from margot.services import push


@fixture
def fake_push_project(tmp_path: Path) -> Path:
    """Create a test project with margo.yaml and pre-built artifacts.

    Structure:
        tmp_path/
          margo.yaml
          .dist/
            1.0.0/
              margo/
                app.yaml
              testapp-1.0.0.tgz  (compose flat / quadlet flat)
            1.0.0_simple/
              testapp-1.0.0_simple.tgz  (compose variant)
    """
    # Create margo.yaml with repository fields
    margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-app
compose:
  directory: compose
  repository: public.ecr.aws/g2n4p2m7/margo-compose
  variants:
    - name: default
      version: 1.0.0
    - name: simple
      version: 1.0.0_simple
quadlet:
  directory: quadlet
  repository: public.ecr.aws/g2n4p2m7/margo-quadlet
  variants:
    - name: default
      version: 1.0.0
"""
    (tmp_path / "margo.yaml").write_text(margo_yaml_content)

    # Create pre-built artifacts in .dist
    dist = tmp_path / ".dist"

    # Margo artifact
    margo_dir = dist / "1.0.0" / "margo"
    margo_dir.mkdir(parents=True)
    (margo_dir / "app.yaml").write_text("name: testapp\n")

    # Compose/quadlet archive for version 1.0.0
    version_dir = dist / "1.0.0"
    (version_dir / "testapp-1.0.0.tgz").write_bytes(b"fake-archive")

    # Compose variant archive for version 1.0.0_simple
    simple_dir = dist / "1.0.0_simple"
    simple_dir.mkdir(parents=True)
    (simple_dir / "testapp-1.0.0_simple.tgz").write_bytes(b"fake-archive-simple")

    return tmp_path


class TestPushMargo:
    """Tests for pushing margo component."""

    def test_push_margo_calls_infra_push_margo(self, mocker: Any, fake_push_project: Path) -> None:
        """Should call OrasClient.push_margo with correct arguments."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        targets = push.push(
            PackageType.MARGO,
            project_dir=str(fake_push_project),
            build_dir=str(fake_push_project / ".dist"),
        )

        assert len(targets) == 1
        assert targets[0].package_type == PackageType.MARGO
        assert targets[0].version == "1.0.0"
        assert targets[0].variant_name is None

        mock_client.push_margo.assert_called_once_with(
            build_dir=str(fake_push_project / ".dist"),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo-app",
            name="testapp",
            description="Test application",
        )

    def test_push_margo_with_cli_registry_overrides(self, mocker: Any, fake_push_project: Path) -> None:
        """Should use CLI registry/repository over margo.yaml values."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.MARGO,
            project_dir=str(fake_push_project),
            build_dir=str(fake_push_project / ".dist"),
            registry="custom.registry.io",
            repository="org/repo",
        )

        mock_client.push_margo.assert_called_once()
        call_kwargs = mock_client.push_margo.call_args[1]
        assert call_kwargs["registry"] == "custom.registry.io"
        assert call_kwargs["repository"] == "org/repo"


class TestPushComposeFlat:
    """Tests for pushing compose component (flat layout)."""

    def test_push_compose_flat(self, mocker: Any, tmp_path: Path) -> None:
        """Should call OrasClient.push_compose with correct archive path for flat layout."""
        margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-compose
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        # Create pre-built artifact
        dist = tmp_path / ".dist" / "1.0.0"
        dist.mkdir(parents=True)
        (dist / "testapp-1.0.0.tgz").write_bytes(b"fake-archive")

        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        targets = push.push(
            PackageType.COMPOSE,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        assert len(targets) == 1
        assert targets[0].package_type == PackageType.COMPOSE
        assert targets[0].version == "1.0.0"
        assert targets[0].variant_name is None

        mock_client.push_compose.assert_called_once_with(
            archive_path=str(dist / "testapp-1.0.0.tgz"),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo-compose",
            name="testapp",
            description="Test application",
        )


class TestPushComposeVariant:
    """Tests for pushing compose component (variant layout)."""

    def test_push_compose_variant(self, mocker: Any, fake_push_project: Path) -> None:
        """Should call OrasClient.push_compose with correct archive path for specific variant."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        targets = push.push(
            PackageType.COMPOSE,
            project_dir=str(fake_push_project),
            build_dir=str(fake_push_project / ".dist"),
            variant="simple",
        )

        assert len(targets) == 1
        assert targets[0].variant_name == "simple"
        assert targets[0].version == "1.0.0_simple"

        mock_client.push_compose.assert_called_once_with(
            archive_path=str(fake_push_project / ".dist" / "1.0.0_simple" / "testapp-1.0.0_simple.tgz"),
            version="1.0.0_simple",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo-compose",
            name="testapp",
            description="Test application",
        )


class TestPushQuadlet:
    """Tests for pushing quadlet component."""

    def test_push_quadlet_calls_infra_push_quadlet(self, mocker: Any, fake_push_project: Path) -> None:
        """Should call OrasClient.push_quadlet with correct arguments."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        targets = push.push(
            PackageType.QUADLET,
            project_dir=str(fake_push_project),
            build_dir=str(fake_push_project / ".dist"),
        )

        assert len(targets) == 1
        assert targets[0].package_type == PackageType.QUADLET
        assert targets[0].version == "1.0.0"
        assert targets[0].variant_name == "default"

        mock_client.push_quadlet.assert_called_once_with(
            archive_path=str(fake_push_project / ".dist" / "1.0.0" / "testapp-1.0.0.tgz"),
            version="1.0.0",
            registry="public.ecr.aws",
            repository="g2n4p2m7/margo-quadlet",
            name="testapp",
            description="Test application",
        )


class TestPushAll:
    """Tests for pushing ALL package types."""

    def test_push_all_calls_all_push_methods(self, mocker: Any, fake_push_project: Path) -> None:
        """Should push margo + all compose variants + all quadlet variants."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        targets = push.push(
            PackageType.ALL,
            project_dir=str(fake_push_project),
            build_dir=str(fake_push_project / ".dist"),
        )

        # 1 margo + 2 compose variants (default + simple) + 1 quadlet variant (default)
        assert len(targets) == 4

        package_types = [t.package_type for t in targets]
        assert package_types.count(PackageType.MARGO) == 1
        assert package_types.count(PackageType.COMPOSE) == 2
        assert package_types.count(PackageType.QUADLET) == 1

        mock_client.push_margo.assert_called_once()
        assert mock_client.push_compose.call_count == 2
        mock_client.push_quadlet.assert_called_once()


class TestPushErrors:
    """Tests for error conditions."""

    def test_push_missing_artifact_raises_value_error(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError when built artifact does not exist."""
        margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-app
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        # No .dist directory — artifact does not exist

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="Built margo artifact not found"):
            push.push(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )

    def test_push_credentials_expired_propagates(self, mocker: Any, fake_push_project: Path) -> None:
        """Should propagate CredentialsExpiredError from credentials check."""
        mocker.patch(
            "margot.services.push.credentials.check_credentials",
            side_effect=CredentialsExpiredError("Credentials for public.ecr.aws have expired."),
        )

        with raises(CredentialsExpiredError, match="expired"):
            push.push(
                PackageType.MARGO,
                project_dir=str(fake_push_project),
                build_dir=str(fake_push_project / ".dist"),
            )

    def test_push_invalid_semver_raises_value_error(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError for invalid semver version before any push."""
        margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: not-semver
  repository: public.ecr.aws/g2n4p2m7/margo-app
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)

        with raises(ValueError, match="not valid SemVer"):
            push.push(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )

        # Should not have attempted to push
        mock_client.push_margo.assert_not_called()

    def test_push_no_registry_raises_value_error(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError when no registry/repository can be resolved."""
        margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="No registry/repository specified"):
            push.push(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )
