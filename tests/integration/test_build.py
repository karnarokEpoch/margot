"""Integration tests for services/build.py."""

from io import StringIO
from pathlib import Path
import re
import tarfile

from pytest import fixture, raises

from margot import console
from margot.domain.models import PackageType
from margot.services import build


@fixture
def fake_project(tmp_path: Path) -> Path:
    """Create a temporary project with margo.yaml and component directories.

    Structure:
        tmp_path/
          margo.yaml
          margo/
            app.yaml (contains <compose_tag> placeholder)
          compose/
            default/
              compose.yaml (contains <margo_tag> placeholder)
            simple/
              compose.yaml
          quadlet/
            default/
              app.container

    Returns:
        Path to tmp_path.
    """
    # Create margo.yaml
    margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
compose:
  directory: compose
  variants:
    - name: default
      version: 1.0.0
    - name: simple
      version: 1.0.0_simple
quadlet:
  directory: quadlet
  variants:
    - name: default
      version: 1.0.0
"""
    (tmp_path / "margo.yaml").write_text(margo_yaml_content)

    # Create margo component
    margo_dir = tmp_path / "margo"
    margo_dir.mkdir()
    (margo_dir / "app.yaml").write_text("image: myapp\ncompose_tag: <compose_tag>\n")

    # Create compose component with variants
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()

    default_compose = compose_dir / "default"
    default_compose.mkdir()
    (default_compose / "compose.yaml").write_text("version: '3'\nservices:\n  margo: <margo_tag>\n")

    simple_compose = compose_dir / "simple"
    simple_compose.mkdir()
    (simple_compose / "compose.yaml").write_text("version: '3'\nservices:\n  app: simple\n")

    # Create quadlet component with variants
    quadlet_dir = tmp_path / "quadlet"
    quadlet_dir.mkdir()

    default_quadlet = quadlet_dir / "default"
    default_quadlet.mkdir()
    (default_quadlet / "app.container").write_text("[Container]\nImage=test:1.0.0\n")

    return tmp_path


class TestBuildMargo:
    """Tests for building margo component."""

    def test_build_margo_single(self, fake_project: Path) -> None:
        """Should build margo component and return BuildTarget."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.MARGO,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )

        assert len(targets) == 1
        target = targets[0]
        assert target.package_type == PackageType.MARGO
        assert target.version == "1.0.0"
        assert target.variant_name is None

        # Verify output directory exists
        output_dir = Path(target.output_dir)
        assert output_dir.exists()
        assert (output_dir / "app.yaml").exists()

    def test_build_margo_with_version_override(self, fake_project: Path) -> None:
        """Should use version_override when provided."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.MARGO,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
            version_override="2.0.0",
        )

        assert len(targets) == 1
        assert targets[0].version == "2.0.0"
        assert (Path(targets[0].output_dir) / "app.yaml").exists()

    def test_build_margo_substitutes_placeholders(self, fake_project: Path) -> None:
        """Should substitute <compose_tag> placeholder in app.yaml."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.MARGO,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )

        app_yaml = Path(targets[0].output_dir) / "app.yaml"
        content = app_yaml.read_text()
        # <compose_tag> should be substituted with margo version
        # In our fixture, compose has no version (only variants), so compose_version = variants[0].version
        assert "<compose_tag>" not in content  # Placeholder should be replaced
        assert "compose_tag: 1.0.0" in content

    def test_build_margo_raises_when_margo_undefined(self, tmp_path: Path) -> None:
        """Should raise ValueError when margo component not defined."""
        # Create minimal margo.yaml without margo component
        (tmp_path / "margo.yaml").write_text("apiVersion: v1\nname: test\ndescription: test\n")

        build_dir = tmp_path / ".dist"
        with raises(ValueError, match="margo component not defined"):
            build.build(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
            )

    def test_build_margo_raises_on_invalid_version(self, fake_project: Path) -> None:
        """Should raise ValueError on invalid SemVer."""
        build_dir = fake_project / ".dist"
        with raises(ValueError, match="is not valid SemVer"):
            build.build(
                PackageType.MARGO,
                project_dir=str(fake_project),
                build_dir=str(build_dir),
                version_override="not-a-semver",
            )

    def test_build_margo_raises_on_invalid_oci_tag(self, fake_project: Path) -> None:
        """Should raise ValueError on invalid OCI tag."""
        build_dir = fake_project / ".dist"
        with raises(ValueError, match="OCI tag"):
            build.build(
                PackageType.MARGO,
                project_dir=str(fake_project),
                build_dir=str(build_dir),
                version_override="invalid@version",
            )


class TestBuildCompose:
    """Tests for building compose component."""

    def test_build_compose_all_variants(self, fake_project: Path) -> None:
        """Should build all variants when variant=None."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.COMPOSE,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )

        assert len(targets) == 2
        versions = {t.version for t in targets}
        variant_names = {t.variant_name for t in targets}

        assert "1.0.0" in versions
        assert "1.0.0_simple" in versions
        assert "default" in variant_names
        assert "simple" in variant_names

        # Verify tarballs exist
        for target in targets:
            output_path = Path(target.output_dir) / f"testapp-{target.version}.tgz"
            assert output_path.exists()

    def test_build_compose_single_variant(self, fake_project: Path) -> None:
        """Should build only specified variant."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.COMPOSE,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
            variant="simple",
        )

        assert len(targets) == 1
        assert targets[0].variant_name == "simple"
        assert targets[0].version == "1.0.0_simple"

    def test_build_compose_substitutes_placeholders(self, fake_project: Path) -> None:
        """Should substitute <margo_tag> in compose files."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.COMPOSE,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
            variant="default",
        )

        # Extract tarball and check content
        tarball_path = Path(targets[0].output_dir) / f"testapp-{targets[0].version}.tgz"
        with tarfile.open(tarball_path, "r:gz") as tar:
            compose_yaml_content = tar.extractfile("compose.yaml").read().decode()
            # <margo_tag> should be replaced with margo version (1.0.0)
            assert "<margo_tag>" not in compose_yaml_content
            assert "margo: 1.0.0" in compose_yaml_content

    def test_build_compose_raises_on_unknown_variant(self, fake_project: Path) -> None:
        """Should raise ValueError for unknown variant name."""
        build_dir = fake_project / ".dist"
        with raises(ValueError, match="variant 'unknown' not declared"):
            build.build(
                PackageType.COMPOSE,
                project_dir=str(fake_project),
                build_dir=str(build_dir),
                variant="unknown",
            )

    def test_build_compose_raises_when_undefined(self, tmp_path: Path) -> None:
        """Should raise ValueError when compose component not defined."""
        (tmp_path / "margo.yaml").write_text("apiVersion: v1\nname: test\ndescription: test\n")

        build_dir = tmp_path / ".dist"
        with raises(ValueError, match="compose component not defined"):
            build.build(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
            )


class TestBuildQuadlet:
    """Tests for building quadlet component."""

    def test_build_quadlet_all_variants(self, fake_project: Path) -> None:
        """Should build all quadlet variants."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.QUADLET,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )

        assert len(targets) == 1
        assert targets[0].variant_name == "default"
        assert targets[0].version == "1.0.0"

    def test_build_quadlet_creates_tarball(self, fake_project: Path) -> None:
        """Should create tarball for quadlet."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.QUADLET,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )

        tarball_path = Path(targets[0].output_dir) / f"testapp-{targets[0].version}.tgz"
        assert tarball_path.exists()


class TestBuildAll:
    """Tests for building ALL package types."""

    def test_build_all_returns_all_targets(self, fake_project: Path) -> None:
        """Should build margo + all compose variants + all quadlet variants."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.ALL,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )

        # 1 margo + 2 compose (default, simple) + 1 quadlet (default)
        assert len(targets) == 4

        package_types = [t.package_type for t in targets]
        assert package_types.count(PackageType.MARGO) == 1
        assert package_types.count(PackageType.COMPOSE) == 2
        assert package_types.count(PackageType.QUADLET) == 1

    def test_build_all_with_version_override(self, fake_project: Path) -> None:
        """Should apply version_override to all components."""
        build_dir = fake_project / ".dist"
        targets = build.build(
            PackageType.ALL,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
            version_override="3.0.0",
        )

        versions = {t.version for t in targets}
        assert versions == {"3.0.0"}


class TestBuildErrors:
    """Tests for error conditions."""

    def test_build_raises_on_missing_margo_yaml(self, tmp_path: Path) -> None:
        """Should raise ValueError when margo.yaml not found."""
        build_dir = tmp_path / ".dist"
        with raises(ValueError, match=re.escape("margo.yaml not found")):
            build.build(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
            )

    def test_build_raises_on_invalid_yaml(self, tmp_path: Path) -> None:
        """Should raise ValueError on invalid YAML syntax."""
        (tmp_path / "margo.yaml").write_text("invalid: yaml: content:")

        build_dir = tmp_path / ".dist"
        with raises(ValueError, match="not valid YAML"):
            build.build(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
            )

    def test_build_compose_flat_with_variant_arg_raises(self, tmp_path: Path) -> None:
        """Should raise ValueError when variant arg used with flat layout."""
        # Create flat compose (no variants)
        margo_yaml = """\
apiVersion: v1
name: test
description: test
compose:
  directory: compose
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml)
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "compose.yaml").write_text("version: '3'\n")

        build_dir = tmp_path / ".dist"
        with raises(ValueError, match="no variants declared"):
            build.build(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
                variant="something",
            )


class TestBuildVerbose:
    """Tests for console output (info messages)."""

    def test_build_emits_info_messages(
        self,
        fake_project: Path,
        capture_console: tuple[StringIO, StringIO],
        reset_console: None,
    ) -> None:
        """Should emit info messages to stderr when verbose."""
        console.set_verbose(True)
        out, err = capture_console

        build_dir = fake_project / ".dist"
        build.build(
            PackageType.MARGO,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )

        err_text = err.getvalue()
        assert "Loaded margo.yaml" in err_text
        assert "Building margo" in err_text
        assert "built:" in err_text
        assert "Build complete" in err_text
        assert out.getvalue() == ""


class TestBuildAllSkipsMissing:
    """Tests for --type all skipping undefined optional components."""

    def test_build_all_skips_missing_compose(self, tmp_path: Path) -> None:
        """Should skip compose when not defined; return 1 MARGO + 1 QUADLET."""
        margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
quadlet:
  directory: quadlet
  variants:
    - name: default
      version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        (margo_dir / "app.yaml").write_text("name: testapp\n")

        quadlet_dir = tmp_path / "quadlet" / "default"
        quadlet_dir.mkdir(parents=True)
        (quadlet_dir / "app.container").write_text("[Container]\nImage=test:1.0.0\n")

        build_dir = tmp_path / ".dist"
        targets = build.build(
            PackageType.ALL,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
        )

        package_types = [t.package_type for t in targets]
        assert package_types.count(PackageType.MARGO) == 1
        assert package_types.count(PackageType.QUADLET) == 1
        assert PackageType.COMPOSE not in package_types

    def test_build_all_skips_missing_quadlet(self, tmp_path: Path) -> None:
        """Should skip quadlet when not defined; return 1 MARGO + 2 COMPOSE."""
        margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
compose:
  directory: compose
  variants:
    - name: default
      version: 1.0.0
    - name: simple
      version: 1.0.0_simple
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        (margo_dir / "app.yaml").write_text("name: testapp\n")

        for variant in ("default", "simple"):
            compose_dir = tmp_path / "compose" / variant
            compose_dir.mkdir(parents=True)
            (compose_dir / "compose.yaml").write_text("version: '3'\n")

        build_dir = tmp_path / ".dist"
        targets = build.build(
            PackageType.ALL,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
        )

        package_types = [t.package_type for t in targets]
        assert package_types.count(PackageType.MARGO) == 1
        assert package_types.count(PackageType.COMPOSE) == 2
        assert PackageType.QUADLET not in package_types

    def test_build_all_skips_all_optional_components(self, tmp_path: Path) -> None:
        """Should return only 1 MARGO when compose and quadlet are not defined."""
        margo_yaml_content = """\
apiVersion: v1
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        (margo_dir / "app.yaml").write_text("name: testapp\n")

        build_dir = tmp_path / ".dist"
        targets = build.build(
            PackageType.ALL,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
        )

        assert len(targets) == 1
        assert targets[0].package_type == PackageType.MARGO


class TestBuildIdempotent:
    """Tests for idempotent rebuild behaviour."""

    def test_build_margo_twice_is_idempotent(self, fake_project: Path) -> None:
        """Second build(MARGO) should succeed and output dir contain expected files."""
        build_dir = fake_project / ".dist"

        targets_1 = build.build(
            PackageType.MARGO,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )
        assert len(targets_1) == 1

        # Second call: must not raise and must still produce the output dir
        targets_2 = build.build(
            PackageType.MARGO,
            project_dir=str(fake_project),
            build_dir=str(build_dir),
        )
        assert len(targets_2) == 1

        output_dir = Path(targets_2[0].output_dir)
        assert output_dir.exists()
        assert (output_dir / "app.yaml").exists()
