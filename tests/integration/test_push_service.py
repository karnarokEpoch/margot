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
id: testapp
name: testapp
description: Test application
version: 1.0.0
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
id: testapp
name: testapp
description: Test application
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
id: testapp
name: testapp
description: Test application
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


class TestPushAllReRaise:
    """Tests for _push_all re-raising non-'not defined' ValueErrors (lines 80-100)."""

    def test_push_all_reraises_margo_non_not_defined_error(self, mocker: Any, fake_push_project: Path) -> None:
        """Should re-raise ValueError from _push_margo if it's not 'not defined'."""
        mocker.patch("margot.services.push.credentials.check_credentials")
        mocker.patch("margot.services.push._push_margo", side_effect=ValueError("disk full"))

        with raises(ValueError, match="disk full"):
            push.push(
                PackageType.ALL,
                project_dir=str(fake_push_project),
                build_dir=str(fake_push_project / ".dist"),
            )

    def test_push_all_reraises_compose_non_not_defined_error(self, mocker: Any, fake_push_project: Path) -> None:
        """Should re-raise ValueError from compose push if it's not 'not defined'."""
        mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)
        mocker.patch(
            "margot.services.push._push_compose_or_quadlet",
            side_effect=ValueError("compose network error"),
        )

        with raises(ValueError, match="compose network error"):
            push.push(
                PackageType.ALL,
                project_dir=str(fake_push_project),
                build_dir=str(fake_push_project / ".dist"),
            )

    def test_push_all_reraises_quadlet_non_not_defined_error(self, mocker: Any, tmp_path: Path) -> None:
        """Should re-raise ValueError from quadlet push if it's not 'not defined'."""
        # Project with margo + compose defined (so they succeed), quadlet raises
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo-app
compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-compose
quadlet:
  directory: quadlet
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-quadlet
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0"
        margo_dir = dist / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("name: test\n")
        (dist / "testapp-1.0.0.tgz").write_bytes(b"fake")

        mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)

        # Make _push_compose_or_quadlet raise only for QUADLET
        original = push._push_compose_or_quadlet  # noqa: SLF001

        def side_effect(*args: Any, **kwargs: Any) -> Any:
            if args[-1] == PackageType.QUADLET:
                raise ValueError("quadlet permission denied")
            return original(*args, **kwargs)

        mocker.patch("margot.services.push._push_compose_or_quadlet", side_effect=side_effect)

        with raises(ValueError, match="quadlet permission denied"):
            push.push(
                PackageType.ALL,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )


class TestPushResolveRegistryRepository:
    """Tests for _resolve_registry_repository edge cases (lines 132-143)."""

    def test_push_with_cli_registry_only_no_component_repo_raises(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise when --registry given but no --repository and no component repository."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0" / "margo"
        dist.mkdir(parents=True)
        (dist / "app.yaml").write_text("name: test\n")

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="--repository is required"):
            push.push(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
                registry="custom.registry.io",
            )

    def test_push_with_cli_repository_only_no_component_repo_raises(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise when --repository given but no --registry and no component repository."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0" / "margo"
        dist.mkdir(parents=True)
        (dist / "app.yaml").write_text("name: test\n")

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="--registry is required"):
            push.push(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
                repository="org/repo",
            )

    def test_push_with_cli_registry_and_component_repo_uses_component_path(self, mocker: Any, tmp_path: Path) -> None:
        """Should use CLI registry + component repository path when only --registry given."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo-app
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0" / "margo"
        dist.mkdir(parents=True)
        (dist / "app.yaml").write_text("name: test\n")

        mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)

        push.push(
            PackageType.MARGO,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
            registry="custom.registry.io",
        )

        call_kwargs = mock_client.push_margo.call_args[1]
        assert call_kwargs["registry"] == "custom.registry.io"
        assert call_kwargs["repository"] == "g2n4p2m7/margo-app"

    def test_push_with_cli_repository_and_component_repo_uses_component_registry(self, mocker: Any, tmp_path: Path) -> None:
        """Should use component registry + CLI repository when only --repository given."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo-app
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0" / "margo"
        dist.mkdir(parents=True)
        (dist / "app.yaml").write_text("name: test\n")

        mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)

        push.push(
            PackageType.MARGO,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
            repository="custom/path",
        )

        call_kwargs = mock_client.push_margo.call_args[1]
        assert call_kwargs["registry"] == "public.ecr.aws"
        assert call_kwargs["repository"] == "custom/path"


class TestPushParseComponentRepository:
    """Tests for _parse_component_repository invalid field (line 166)."""

    def test_push_margo_invalid_repository_no_slash_raises(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError when component repository has no slash."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
repository: noslash
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0" / "margo"
        dist.mkdir(parents=True)
        (dist / "app.yaml").write_text("name: test\n")

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="Cannot parse"):
            push.push(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )


class TestPushFlatComponentErrors:
    """Tests for _push_flat_component errors (lines 259, 263)."""

    def test_push_flat_compose_variant_not_supported_raises(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError when variant arg used with flat compose layout."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-compose
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="--variant not supported"):
            push.push(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
                variant="foo",
            )

    def test_push_flat_compose_version_none_raises(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError when flat compose version is None."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
compose:
  directory: compose
  repository: public.ecr.aws/g2n4p2m7/margo-compose
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="version not specified"):
            push.push(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )


class TestPushFlatComponentCredentials:
    """Tests for _push_flat_component credentials check (line 281)."""

    def test_push_flat_compose_checks_credentials(self, mocker: Any, tmp_path: Path) -> None:
        """Should call credentials.check_credentials for flat compose push."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-compose
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0"
        dist.mkdir(parents=True)
        (dist / "testapp-1.0.0.tgz").write_bytes(b"fake")

        check_creds = mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)

        push.push(
            PackageType.COMPOSE,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        # Credentials check should have been called with the resolved registry
        check_creds.assert_called_with("public.ecr.aws")


class TestPushVariantComponentCredentials:
    """Tests for _push_variant_component credentials check (line 326) and loop body (line 348)."""

    def test_push_variant_compose_checks_credentials(self, mocker: Any, fake_push_project: Path) -> None:
        """Should call credentials.check_credentials for each variant push."""
        check_creds = mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)

        push.push(
            PackageType.COMPOSE,
            project_dir=str(fake_push_project),
            build_dir=str(fake_push_project / ".dist"),
        )

        # Called once per variant (2 variants: default + simple)
        assert check_creds.call_count == 2


class TestPushQuadletComponent:
    """Tests for _push_compose_or_quadlet with quadlet (line 236)."""

    def test_push_quadlet_flat_success(self, mocker: Any, tmp_path: Path) -> None:
        """Should push flat quadlet component successfully."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
quadlet:
  directory: quadlet
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-quadlet
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0"
        dist.mkdir(parents=True)
        (dist / "testapp-1.0.0.tgz").write_bytes(b"fake")

        mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)

        targets = push.push(
            PackageType.QUADLET,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        assert len(targets) == 1
        assert targets[0].package_type == PackageType.QUADLET
        assert targets[0].variant_name is None
        mock_client.push_quadlet.assert_called_once()


class TestPushAllSkipsCompose:
    """Test _push_all skipping compose when not defined (line 90)."""

    def test_push_all_skips_undefined_compose(self, mocker: Any, tmp_path: Path) -> None:
        """Should skip compose when not defined; return margo + quadlet targets."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo-app
quadlet:
  directory: quadlet
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-quadlet
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        dist = tmp_path / ".dist" / "1.0.0"
        margo_dir = dist / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("name: test\n")
        (dist / "testapp-1.0.0.tgz").write_bytes(b"fake")

        mocker.patch("margot.services.push.credentials.check_credentials")
        mock_client = MagicMock()
        mocker.patch("margot.services.push.oci.OrasClient", return_value=mock_client)

        targets = push.push(
            PackageType.ALL,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        package_types = [t.package_type for t in targets]
        assert PackageType.MARGO in package_types
        assert PackageType.COMPOSE not in package_types
        assert PackageType.QUADLET in package_types


class TestPushFlatComponentMissingArtifact:
    """Test _push_flat_component when artifact not found (line 281)."""

    def test_push_flat_compose_missing_archive_raises(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError when flat compose archive does not exist."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo-compose
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        # No .dist directory — artifact does not exist

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="Built compose artifact not found"):
            push.push(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
            )


class TestPushVariantComponentErrors:
    """Tests for _push_variant_component error paths (lines 326, 348)."""

    def test_push_variant_compose_unknown_variant_raises(self, mocker: Any, fake_push_project: Path) -> None:
        """Should raise ValueError for unknown variant name."""
        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="variant 'nonexistent' not declared"):
            push.push(
                PackageType.COMPOSE,
                project_dir=str(fake_push_project),
                build_dir=str(fake_push_project / ".dist"),
                variant="nonexistent",
            )

    def test_push_variant_compose_missing_archive_raises(self, mocker: Any, tmp_path: Path) -> None:
        """Should raise ValueError when variant archive does not exist."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
compose:
  directory: compose
  repository: public.ecr.aws/g2n4p2m7/margo-compose
  variants:
    - name: default
      version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        # No .dist directory — artifact does not exist

        mocker.patch("margot.services.push.credentials.check_credentials")

        with raises(ValueError, match="Built compose artifact not found"):
            push.push(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(tmp_path / ".dist"),
                variant="default",
            )
