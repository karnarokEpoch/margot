"""Integration tests for services/push.py dry_run functionality."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

from pytest import fixture, raises

from margot.domain.models import PackageType
from margot.infra.credentials import CredentialsExpiredError
from margot.services import push


@fixture
def dry_run_project(tmp_path: Path) -> Path:
    """Create a test project for dry_run tests."""
    margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
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

    # Create pre-built artifacts
    dist = tmp_path / ".dist"

    # Margo artifact
    margo_dir = dist / "1.0.0" / "margo"
    margo_dir.mkdir(parents=True)
    (margo_dir / "app.yaml").write_text("name: testapp\n")

    # Compose artifacts
    version_dir = dist / "1.0.0"
    (version_dir / "testapp-1.0.0.tgz").write_bytes(b"fake-archive")

    simple_dir = dist / "1.0.0_simple"
    simple_dir.mkdir(parents=True)
    (simple_dir / "testapp-1.0.0_simple.tgz").write_bytes(b"fake-archive-simple")

    # Quadlet artifacts
    (version_dir / "testapp-1.0.0.tgz").write_bytes(b"fake-quadlet-archive")

    return tmp_path


class TestDryRunMargo:
    """Tests for dry_run with margo component."""

    def test_dry_run_margo_calls_check_write_access(self, mocker: Any, dry_run_project: Path) -> None:
        """Should call check_write_access instead of push_margo when dry_run=True."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.MARGO,
            project_dir=str(dry_run_project),
            build_dir=str(dry_run_project / ".dist"),
            dry_run=True,
        )

        mock_client.push_margo.assert_not_called()
        mock_client.check_write_access.assert_called_once_with("public.ecr.aws", "g2n4p2m7/margo-app")

    def test_dry_run_false_margo_calls_push_margo(self, mocker: Any, dry_run_project: Path) -> None:
        """Should call push_margo when dry_run=False (default behavior)."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.MARGO,
            project_dir=str(dry_run_project),
            build_dir=str(dry_run_project / ".dist"),
            dry_run=False,
        )

        mock_client.push_margo.assert_called_once()
        mock_client.check_write_access.assert_not_called()


class TestDryRunCompose:
    """Tests for dry_run with compose component."""

    def test_dry_run_compose_deduplicates_write_access_probe(self, mocker: Any, dry_run_project: Path) -> None:
        """Should probe write access only once per (registry, repository) pair when pushing multiple variants."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.COMPOSE,
            project_dir=str(dry_run_project),
            build_dir=str(dry_run_project / ".dist"),
            dry_run=True,
        )

        # Should be called once for the two variants (both share same registry/repo)
        assert mock_client.check_write_access.call_count == 1
        mock_client.check_write_access.assert_called_with("public.ecr.aws", "g2n4p2m7/margo-compose")


class TestDryRunAll:
    """Tests for dry_run with ALL package type."""

    def test_dry_run_all_deduplicates_probes(self, mocker: Any, dry_run_project: Path) -> None:
        """Should deduplicate write access probes across multiple components when using ALL."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        push.push(
            PackageType.ALL,
            project_dir=str(dry_run_project),
            build_dir=str(dry_run_project / ".dist"),
            dry_run=True,
        )

        # Should be 3 unique probes: margo, compose, quadlet
        expected_calls = [
            call("public.ecr.aws", "g2n4p2m7/margo-app"),
            call("public.ecr.aws", "g2n4p2m7/margo-compose"),
            call("public.ecr.aws", "g2n4p2m7/margo-quadlet"),
        ]
        mock_client.check_write_access.assert_has_calls(expected_calls)
        assert mock_client.check_write_access.call_count == 3


class TestDryRunValidation:
    """Tests that dry_run still validates like normal mode."""

    def test_dry_run_validates_artifact_exists(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError when artifact missing, even in dry_run mode."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
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
                dry_run=True,
            )

    def test_dry_run_checks_credentials(self, mocker: Any, dry_run_project: Path) -> None:
        """Should check credentials even in dry_run mode."""
        mocker.patch(
            "margot.services.push.credentials.check_credentials",
            side_effect=CredentialsExpiredError("Credentials expired"),
        )

        with raises(CredentialsExpiredError, match="Credentials expired"):
            push.push(
                PackageType.MARGO,
                project_dir=str(dry_run_project),
                build_dir=str(dry_run_project / ".dist"),
                dry_run=True,
            )

    def test_dry_run_validates_semver(self, mocker: Any, tmp_path: Path) -> None:
        """Should validate semver even in dry_run mode."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: not-semver
repository: public.ecr.aws/g2n4p2m7/margo-app
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="not valid SemVer"):
            push.push(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
                dry_run=True,
            )


class TestDryRunReturnValue:
    """Tests that dry_run returns BuildTarget like normal mode."""

    def test_dry_run_returns_build_targets(self, mocker: Any, dry_run_project: Path) -> None:
        """Should return BuildTarget objects with same structure in dry_run mode."""
        mock_client = MagicMock()
        mocker.patch("margot.services.push.OrasClient", return_value=mock_client)
        mocker.patch("margot.services.push.credentials.check_credentials")

        targets = push.push(
            PackageType.MARGO,
            project_dir=str(dry_run_project),
            build_dir=str(dry_run_project / ".dist"),
            dry_run=True,
        )

        assert len(targets) == 1
        assert targets[0].package_type == PackageType.MARGO
        assert targets[0].version == "1.0.0"
        assert targets[0].registry == "public.ecr.aws"
        assert targets[0].repository == "g2n4p2m7/margo-app"
