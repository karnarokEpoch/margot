"""Unit tests for push service: verify OrasClient receives correct hostname argument.

Tests that verify the registry hostname is correctly passed to OrasClient
so that stored credentials are loaded and used for authentication.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

from pytest import fixture

from margot.domain.models import PackageType
from margot.services import push


@fixture
def test_project_minimal(tmp_path: Path) -> Path:
    """Create a minimal test project with pre-built artifacts."""
    # Margo artifact
    margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test app
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo-app
"""
    (tmp_path / "margo.yaml").write_text(margo_yaml_content)

    dist = tmp_path / ".dist"
    margo_dir = dist / "1.0.0" / "margo"
    margo_dir.mkdir(parents=True)
    (margo_dir / "app.yaml").write_text("name: testapp\n")

    return tmp_path


class TestPushMargoClientHostname:
    """Tests for _push_margo passing hostname to OrasClient."""

    def test_push_margo_oras_client_receives_resolved_registry_as_hostname(
        self, mocker: Any, test_project_minimal: Path
    ) -> None:
        """Should construct OrasClient with hostname=resolved_registry."""
        mock_oras_client_class = mocker.patch("margot.services.push.oci.OrasClient")
        mock_oras_instance = MagicMock()
        mock_oras_client_class.return_value = mock_oras_instance
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.MARGO,
            project_dir=str(test_project_minimal),
            build_dir=str(test_project_minimal / ".dist"),
        )

        # Verify OrasClient was instantiated with hostname kwarg
        mock_oras_client_class.assert_called_once_with(hostname="public.ecr.aws")

    def test_push_margo_with_cli_registry_passes_cli_registry_as_hostname(
        self, mocker: Any, test_project_minimal: Path
    ) -> None:
        """Should use CLI registry as hostname when --registry flag provided."""
        mock_oras_client_class = mocker.patch("margot.services.push.oci.OrasClient")
        mock_oras_instance = MagicMock()
        mock_oras_client_class.return_value = mock_oras_instance
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.MARGO,
            project_dir=str(test_project_minimal),
            build_dir=str(test_project_minimal / ".dist"),
            registry="custom.registry.io",
            repository="org/repo",
        )

        # Verify OrasClient was instantiated with the CLI registry as hostname
        mock_oras_client_class.assert_called_once_with(hostname="custom.registry.io")


class TestPushFlatComponentClientHostname:
    """Tests for _push_flat_component passing hostname to OrasClient."""

    def test_push_flat_compose_oras_client_receives_resolved_registry_as_hostname(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Should construct OrasClient with hostname=resolved_registry for flat compose."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test app
version: 1.0.0
compose:
  directory: compose
  version: 1.0.0
  repository: registry.example.com/my-org/compose-app
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0"
        dist.mkdir(parents=True)
        (dist / "testapp-1.0.0.tgz").write_bytes(b"fake-archive")

        mock_oras_client_class = mocker.patch("margot.services.push.oci.OrasClient")
        mock_oras_instance = MagicMock()
        mock_oras_client_class.return_value = mock_oras_instance
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.COMPOSE,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        # Verify OrasClient was instantiated with the resolved registry as hostname
        mock_oras_client_class.assert_called_once_with(hostname="registry.example.com")

    def test_push_flat_quadlet_oras_client_receives_resolved_registry_as_hostname(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Should construct OrasClient with hostname=resolved_registry for flat quadlet."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test app
version: 1.0.0
quadlet:
  directory: quadlet
  version: 1.0.0
  repository: ecr.aws/namespace/quadlet-app
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0"
        dist.mkdir(parents=True)
        (dist / "testapp-1.0.0.tgz").write_bytes(b"fake-archive")

        mock_oras_client_class = mocker.patch("margot.services.push.oci.OrasClient")
        mock_oras_instance = MagicMock()
        mock_oras_client_class.return_value = mock_oras_instance
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.QUADLET,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        # Verify OrasClient was instantiated with the resolved registry as hostname
        mock_oras_client_class.assert_called_once_with(hostname="ecr.aws")


class TestPushVariantComponentClientHostname:
    """Tests for _push_variant_component passing hostname to OrasClient."""

    def test_push_variant_compose_oras_client_receives_resolved_registry_as_hostname(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Should construct OrasClient with hostname=resolved_registry for each variant."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test app
version: 1.0.0
compose:
  directory: compose
  repository: myregistry.io/compose
  variants:
    - name: default
      version: 1.0.0
    - name: minimal
      version: 1.0.0_minimal
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        dist = tmp_path / ".dist"
        (dist / "1.0.0").mkdir(parents=True)
        (dist / "1.0.0" / "testapp-1.0.0.tgz").write_bytes(b"fake-default")
        (dist / "1.0.0_minimal").mkdir(parents=True)
        (dist / "1.0.0_minimal" / "testapp-1.0.0_minimal.tgz").write_bytes(b"fake-minimal")

        mock_oras_client_class = mocker.patch("margot.services.push.oci.OrasClient")
        mock_oras_instance = MagicMock()
        mock_oras_client_class.return_value = mock_oras_instance
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.COMPOSE,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        # OrasClient should be instantiated once per variant, each with the same hostname
        assert mock_oras_client_class.call_count == 2
        # Check each call received the correct hostname
        assert mock_oras_client_class.call_args_list[0] == call(hostname="myregistry.io")
        assert mock_oras_client_class.call_args_list[1] == call(hostname="myregistry.io")

    def test_push_variant_quadlet_oras_client_receives_resolved_registry_as_hostname(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Should construct OrasClient with hostname=resolved_registry for each variant."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test app
version: 1.0.0
quadlet:
  directory: quadlet
  repository: quay.io/my-org/quadlet
  variants:
    - name: prod
      version: 1.0.0_prod
    - name: staging
      version: 1.0.0_staging
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        dist = tmp_path / ".dist"
        (dist / "1.0.0_prod").mkdir(parents=True)
        (dist / "1.0.0_prod" / "testapp-1.0.0_prod.tgz").write_bytes(b"fake-prod")
        (dist / "1.0.0_staging").mkdir(parents=True)
        (dist / "1.0.0_staging" / "testapp-1.0.0_staging.tgz").write_bytes(b"fake-staging")

        mock_oras_client_class = mocker.patch("margot.services.push.oci.OrasClient")
        mock_oras_instance = MagicMock()
        mock_oras_client_class.return_value = mock_oras_instance
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.QUADLET,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        # OrasClient should be instantiated once per variant, each with the same hostname
        assert mock_oras_client_class.call_count == 2
        # Check each call received the correct hostname
        assert mock_oras_client_class.call_args_list[0] == call(hostname="quay.io")
        assert mock_oras_client_class.call_args_list[1] == call(hostname="quay.io")

    def test_push_single_variant_oras_client_receives_hostname(self, mocker: Any, tmp_path: Path) -> None:
        """Should construct OrasClient with hostname when pushing a single variant."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test app
version: 1.0.0
compose:
  directory: compose
  repository: another-registry.net/compose
  variants:
    - name: default
      version: 1.0.0
    - name: lite
      version: 1.0.0_lite
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        dist = tmp_path / ".dist"
        (dist / "1.0.0").mkdir(parents=True)
        (dist / "1.0.0" / "testapp-1.0.0.tgz").write_bytes(b"fake-default")
        (dist / "1.0.0_lite").mkdir(parents=True)
        (dist / "1.0.0_lite" / "testapp-1.0.0_lite.tgz").write_bytes(b"fake-lite")

        mock_oras_client_class = mocker.patch("margot.services.push.oci.OrasClient")
        mock_oras_instance = MagicMock()
        mock_oras_client_class.return_value = mock_oras_instance
        mocker.patch("margot.services.push.credentials.check_credentials")

        # Push only the "lite" variant
        push.push(
            PackageType.COMPOSE,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
            variant="lite",
        )

        # OrasClient should be instantiated once with the resolved registry
        mock_oras_client_class.assert_called_once_with(hostname="another-registry.net")
