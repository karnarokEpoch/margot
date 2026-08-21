"""Integration tests for services/build.py."""

from io import StringIO
from pathlib import Path
import re
import tarfile
from typing import Any

from pytest import fixture, raises

from margot import console
from margot.domain.metadata import ComponentConfig, MargoYaml
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
id: testapp
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
    (margo_dir / "app.yaml.jinja").write_text(
        "image: {{ manifest.appVersion }}\ncompose_tag: {{ manifest.compose.variants[0].tag }}\n"
    )

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

    def test_build_margo_renders_jinja_template(self, fake_project: Path) -> None:
        """Should render app.yaml.jinja and exclude its source from the build output."""
        build_dir = fake_project / ".dist"
        targets = build.build(PackageType.MARGO, project_dir=str(fake_project), build_dir=str(build_dir))

        output_dir = Path(targets[0].output_dir)
        assert (output_dir / "app.yaml").read_text() == "image: \ncompose_tag: 1.0.0"
        assert not (output_dir / "app.yaml.jinja").exists()

    def test_build_margo_raises_when_margo_undefined(self, tmp_path: Path) -> None:
        """Should raise ValueError when margo component not defined."""
        # Create minimal margo.yaml without margo component
        (tmp_path / "margo.yaml").write_text("apiVersion: v1\nid: testapp\nname: test\ndescription: test\n")

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

    def test_build_margo_renders_app_version(self, tmp_path: Path) -> None:
        """Should render appVersion from margo.yaml in app.yaml.jinja."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
appVersion: "2.5.0"
margo:
  directory: margo
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)

        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        (margo_dir / "app.yaml.jinja").write_text("app: {{ manifest.appVersion }}\n")

        build_dir = tmp_path / ".dist"
        targets = build.build(
            PackageType.MARGO,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
        )

        assert (Path(targets[0].output_dir) / "app.yaml").read_text() == "app: 2.5.0"

    def test_build_placeholder_map_excludes_margo_version(self) -> None:
        """_build_placeholder_map should not contain <margo_version> key; <app_tag> equals app_version."""
        meta = MargoYaml(
            api_version="v1",
            id="testapp",
            name="test-app",
            description="Test",
            app_version="3.1.0",
            annotations={},
            margo=None,
            compose=None,
            quadlet=None,
        )

        result = build._build_placeholder_map(meta, None)  # noqa: SLF001

        assert "<margo_version>" not in result
        assert "<app_tag>" in result
        assert result["<app_tag>"] == "3.1.0"

    def test_build_placeholder_map_version_override_applies_to_defined_components(self) -> None:
        """version_override should apply to defined components, not undefined ones."""
        meta = MargoYaml(
            api_version="v1",
            id="testapp",
            name="test-app",
            description="Test",
            app_version=None,
            annotations={},
            margo=ComponentConfig(directory="margo", version="1.0.0", repository=None, variants=()),
            compose=None,
            quadlet=None,
        )

        result = build._build_placeholder_map(meta, "2.0.0")  # noqa: SLF001

        assert result["<margo_tag>"] == "2.0.0"
        assert result["<compose_tag>"] == ""
        assert result["<quadlet_tag>"] == ""

    def test_build_placeholder_map_version_override_ignored_for_undefined_components(self) -> None:
        """version_override should not populate compose/quadlet tags when those components are undefined."""
        meta = MargoYaml(
            api_version="v1",
            id="testapp",
            name="test-app",
            description="Test",
            app_version=None,
            annotations={},
            margo=None,
            compose=None,
            quadlet=None,
        )

        result = build._build_placeholder_map(meta, "9.9.9")  # noqa: SLF001

        # margo_version uses `or` chaining (not ternary), so version_override applies even when margo=None
        assert result["<margo_tag>"] == "9.9.9"
        # compose/quadlet use ternary: `... if meta.compose else ""` — short-circuits before version_override
        assert result["<compose_tag>"] == ""
        assert result["<quadlet_tag>"] == ""


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
        (tmp_path / "margo.yaml").write_text("apiVersion: v1\nid: testapp\nname: test\ndescription: test\n")

        build_dir = tmp_path / ".dist"
        with raises(ValueError, match="compose component not defined"):
            build.build(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
            )


class TestBuildQuadlet:
    """Tests for building quadlet component."""

    def test_build_quadlet_uses_default_directory_when_omitted(self, tmp_path: Path) -> None:
        """Should build from the default quadlet directory when it is omitted from margo.yaml."""
        (tmp_path / "margo.yaml").write_text(
            "apiVersion: v1\nid: testapp\nname: testapp\ndescription: Test application\nquadlet:\n"
            "  version: 1.0.0\n"
        )
        quadlet_dir = tmp_path / "quadlet"
        quadlet_dir.mkdir()
        (quadlet_dir / "app.container").write_text("[Container]\nImage=test:1.0.0\n")

        targets = build.build(
            PackageType.QUADLET,
            project_dir=str(tmp_path),
            build_dir=str(tmp_path / ".dist"),
        )

        assert len(targets) == 1
        assert (Path(targets[0].output_dir) / "testapp-1.0.0.tgz").exists()

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
id: testapp
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
id: testapp
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
id: testapp
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
id: testapp
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


class TestBuildAllReRaise:
    """Tests for _build_all re-raising non-'not defined' ValueErrors."""

    def test_build_all_reraises_margo_non_not_defined_error(self, mocker: Any, fake_project: Path) -> None:
        """Should re-raise ValueError from _build_margo if it's not 'not defined'."""
        mocker.patch(
            "margot.services.build._build_margo",
            side_effect=ValueError("some other error"),
        )

        build_dir = fake_project / ".dist"
        with raises(ValueError, match="some other error"):
            build.build(
                PackageType.ALL,
                project_dir=str(fake_project),
                build_dir=str(build_dir),
            )

    def test_build_all_reraises_compose_non_not_defined_error(self, mocker: Any, fake_project: Path) -> None:
        """Should re-raise ValueError from compose if it's not 'not defined'."""
        mocker.patch(
            "margot.services.build._build_compose_or_quadlet",
            side_effect=ValueError("compose broke unexpectedly"),
        )

        build_dir = fake_project / ".dist"
        with raises(ValueError, match="compose broke unexpectedly"):
            build.build(
                PackageType.ALL,
                project_dir=str(fake_project),
                build_dir=str(build_dir),
            )

    def test_build_all_reraises_quadlet_non_not_defined_error(self, mocker: Any, tmp_path: Path) -> None:
        """Should re-raise ValueError from quadlet if it's not 'not defined'."""
        # Use a project with margo + compose defined (so they succeed) and quadlet that raises
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
compose:
  directory: compose
  version: 1.0.0
quadlet:
  directory: quadlet
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        (margo_dir / "app.yaml").write_text("name: test\n")
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "compose.yaml").write_text("version: '3'\n")
        quadlet_dir = tmp_path / "quadlet"
        quadlet_dir.mkdir()
        (quadlet_dir / "app.container").write_text("[Container]\n")

        # Patch _build_compose_or_quadlet to fail only for QUADLET
        original_build = build._build_compose_or_quadlet  # noqa: SLF001

        def patched_build(*args: Any, **kwargs: Any) -> Any:
            # args[-2] is component_type in the positional call
            if args[-2] == PackageType.QUADLET:
                raise ValueError("quadlet disk full error")
            return original_build(*args, **kwargs)

        mocker.patch("margot.services.build._build_compose_or_quadlet", side_effect=patched_build)

        build_dir = tmp_path / ".dist"
        with raises(ValueError, match="quadlet disk full error"):
            build.build(
                PackageType.ALL,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
            )


class TestBuildAllSkipsQuadlet:
    """Test _build_all skipping quadlet when not defined (line 102)."""

    def test_build_all_skips_undefined_quadlet(self, tmp_path: Path) -> None:
        """Should skip quadlet when not defined; return margo + compose targets."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
margo:
  directory: margo
  version: 1.0.0
compose:
  directory: compose
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        (margo_dir / "app.yaml").write_text("name: testapp\n")
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "compose.yaml").write_text("version: '3'\n")

        build_dir = tmp_path / ".dist"
        targets = build.build(
            PackageType.ALL,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
        )

        package_types = [t.package_type for t in targets]
        assert PackageType.MARGO in package_types
        assert PackageType.COMPOSE in package_types
        assert PackageType.QUADLET not in package_types


class TestBuildMargoVersionNone:
    """Test _build_margo with version None (line 181)."""

    def test_build_margo_raises_when_version_not_specified(self, tmp_path: Path) -> None:
        """Should raise ValueError when margo version is None and no override."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
margo:
  directory: margo
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        margo_dir = tmp_path / "margo"
        margo_dir.mkdir()
        (margo_dir / "app.yaml").write_text("name: testapp\n")

        build_dir = tmp_path / ".dist"
        with raises(ValueError, match="margo version not specified"):
            build.build(
                PackageType.MARGO,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
            )


class TestBuildFlatCompose:
    """Tests for _build_flat_component success path (lines 271-294)."""

    def test_build_flat_compose_success(self, tmp_path: Path) -> None:
        """Should build flat compose (no variants) and return a single BuildTarget."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
compose:
  directory: compose
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "compose.yaml").write_text("version: '3'\nservices:\n  app: test\n")

        build_dir = tmp_path / ".dist"
        targets = build.build(
            PackageType.COMPOSE,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
        )

        assert len(targets) == 1
        assert targets[0].package_type == PackageType.COMPOSE
        assert targets[0].version == "1.0.0"
        assert targets[0].variant_name is None

        # Verify tarball exists
        tarball = Path(targets[0].output_dir) / "testapp-1.0.0.tgz"
        assert tarball.exists()

    def test_build_flat_compose_version_none_raises(self, tmp_path: Path) -> None:
        """Should raise ValueError when flat compose version is None."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
compose:
  directory: compose
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "compose.yaml").write_text("version: '3'\n")

        build_dir = tmp_path / ".dist"
        with raises(ValueError, match="compose version not specified"):
            build.build(
                PackageType.COMPOSE,
                project_dir=str(tmp_path),
                build_dir=str(build_dir),
            )


class TestBuildAllSkipsMargo:
    """Test _build_all skipping margo when not defined (line 88)."""

    def test_build_all_skips_undefined_margo(self, tmp_path: Path) -> None:
        """Should skip margo when not defined; return only compose targets."""
        margo_yaml_content = """\
apiVersion: v1
id: testapp
name: testapp
description: Test application
compose:
  directory: compose
  version: 1.0.0
"""
        (tmp_path / "margo.yaml").write_text(margo_yaml_content)
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "compose.yaml").write_text("version: '3'\n")

        build_dir = tmp_path / ".dist"
        targets = build.build(
            PackageType.ALL,
            project_dir=str(tmp_path),
            build_dir=str(build_dir),
        )

        package_types = [t.package_type for t in targets]
        assert PackageType.MARGO not in package_types
        assert PackageType.COMPOSE in package_types

    def test_margo_descriptor_resolution_errors_and_static_copy(self, tmp_path: Path) -> None:
        """Static descriptors copy unchanged while missing, duplicate, and undefined templates fail."""

        def write_project(app_files: dict[str, str]) -> Path:
            project = tmp_path / str(len(list(tmp_path.iterdir())))
            project.mkdir()
            (project / "margo.yaml").write_text(
                "apiVersion: v1\nid: testapp\nname: testapp\ndescription: test\nmargo:\n  directory: margo\n  version: 1.0.0\n"
            )
            source = project / "margo"
            source.mkdir()
            for name, content in app_files.items():
                (source / name).write_text(content)
            return project

        static_project = write_project({"app.yaml": "literal: <app_tag>\n"})
        target = build.build(PackageType.MARGO, project_dir=str(static_project), build_dir=str(static_project / ".dist"))[0]
        assert (Path(target.output_dir) / "app.yaml").read_text() == "literal: <app_tag>\n"

        duplicate_project = write_project({"app.yaml": "a", "app.yaml.jinja": "b"})
        with raises(ValueError, match=r"Both app\.yaml\.jinja and app\.yaml"):
            build.build(PackageType.MARGO, project_dir=str(duplicate_project), build_dir=str(duplicate_project / ".dist"))

        missing_project = write_project({})
        with raises(ValueError, match=r"No app\.yaml or app\.yaml\.jinja"):
            build.build(PackageType.MARGO, project_dir=str(missing_project), build_dir=str(missing_project / ".dist"))

        undefined_project = write_project({"app.yaml.jinja": "value: {{ manifest.undefined_var }}"})
        with raises(ValueError, match="Unresolved Jinja2 variable"):
            build.build(PackageType.MARGO, project_dir=str(undefined_project), build_dir=str(undefined_project / ".dist"))

    def test_compose_image_configuration_and_variant_override(self, tmp_path: Path) -> None:
        """Component image substitutions apply unless an individual variant overrides them."""
        (tmp_path / "margo.yaml").write_text(
            "apiVersion: v1\nid: testapp\nname: testapp\ndescription: test\nappVersion: 2.0.0\ncompose:\n"
            "  directory: compose\n  image:\n    search: app:dev\n    replace: registry/app:<app_tag>\n  variants:\n"
            "    - name: default\n      version: 1.0.0\n    - name: gpu\n      version: 1.0.0_gpu\n"
            "      image:\n        search: gpu:dev\n        replace: registry/gpu:<app_tag>\n"
        )
        for variant, image in (("default", "app:dev"), ("gpu", "gpu:dev")):
            source = tmp_path / "compose" / variant
            source.mkdir(parents=True)
            (source / "compose.yaml").write_text(f"image: {image}\n")
        targets = build.build(PackageType.COMPOSE, project_dir=str(tmp_path), build_dir=str(tmp_path / ".dist"))
        contents = {}
        for target in targets:
            with tarfile.open(Path(target.output_dir) / f"testapp-{target.version}.tgz", "r:gz") as archive:
                contents[target.variant_name] = archive.extractfile("compose.yaml").read().decode()
        assert contents["default"] == "image: registry/app:2.0.0\n"
        assert contents["gpu"] == "image: registry/gpu:2.0.0\n"

    def test_compose_without_image_is_unchanged_and_unmatched_image_warns(
        self, tmp_path: Path, capture_console: tuple[StringIO, StringIO]
    ) -> None:
        """No image block is a no-op, and an unmatched configured literal warns without failing."""
        (tmp_path / "margo.yaml").write_text(
            "apiVersion: v1\nid: testapp\nname: testapp\ndescription: test\ncompose:\n  directory: compose\n"
            "  version: 1.0.0\n  image:\n    search: absent:dev\n    replace: registry/app:1.0.0\n"
        )
        source = tmp_path / "compose"
        source.mkdir()
        (source / "compose.yaml").write_text("image: unchanged:dev\n")
        targets = build.build(PackageType.COMPOSE, project_dir=str(tmp_path), build_dir=str(tmp_path / ".dist"))
        with tarfile.open(Path(targets[0].output_dir) / "testapp-1.0.0.tgz", "r:gz") as archive:
            assert archive.extractfile("compose.yaml").read().decode() == "image: unchanged:dev\n"
        assert "Image search string 'absent:dev' not found" in capture_console[1].getvalue()
