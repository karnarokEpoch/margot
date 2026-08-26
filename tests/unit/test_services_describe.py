"""Unit tests for the describe service — descriptor resolution and load gate."""

from pathlib import Path
from tempfile import TemporaryDirectory

from pytest import fixture, raises

from margot.services import describe as describe_service


MARGO_YAML = """apiVersion: v1
id: hello-world
name: Hello World
description: A sample application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo
compose:
  directory: margo
  version: 1.0.0
"""

VALID_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: ApplicationDescription
id: hello-world
metadata:
  name: Hello World
  version: 1.0.0
deploymentProfiles:
  - type: compose
    id: default
    components: []
"""

TEMPLATED_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: {{ manifest.name }}
  version: {{ manifest.version }}
deploymentProfiles:
  - type: compose
    id: default
    components: []
"""

WRONG_KIND_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: SomethingElse
id: hello-world
metadata:
  name: Hello World
  version: 1.0.0
"""

NOT_A_MAPPING_APP_YAML = """
- hello
- world
"""


@fixture
def temp_project() -> Path:
    """Create a temporary project directory with margo.yaml and margo subdirectory."""
    with TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        (project_dir / "margo.yaml").write_text(MARGO_YAML, encoding="utf-8")
        (project_dir / "margo").mkdir()
        yield project_dir


class TestDescribeServiceStaticDescriptor:
    """Tests for load_descriptor with a static app.yaml."""

    def test_load_descriptor_returns_dict(self, temp_project: Path) -> None:
        """Should load a valid descriptor into a dict."""
        (temp_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = describe_service.load_descriptor(str(temp_project))

        assert isinstance(result, dict)
        assert result.get("kind") == "ApplicationDescription"
        assert result.get("id") == "hello-world"

    def test_load_descriptor_missing_file_raises_valueerror(self, temp_project: Path) -> None:
        """Should raise ValueError when neither app.yaml nor app.yaml.jinja exists."""
        with raises(ValueError, match="No app.yaml or app.yaml.jinja found"):
            describe_service.load_descriptor(str(temp_project))

    def test_load_descriptor_both_forms_present_raises_valueerror(self, temp_project: Path) -> None:
        """Should raise ValueError when both app.yaml and app.yaml.jinja are present."""
        (temp_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")
        (temp_project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        with raises(ValueError, match="Both app.yaml.jinja and app.yaml found"):
            describe_service.load_descriptor(str(temp_project))

    def test_load_descriptor_wrong_kind_raises_valueerror(self, temp_project: Path) -> None:
        """Should raise ValueError when kind is not ApplicationDescription."""
        (temp_project / "margo" / "app.yaml").write_text(WRONG_KIND_APP_YAML, encoding="utf-8")

        with raises(ValueError, match="kind.*ApplicationDescription"):
            describe_service.load_descriptor(str(temp_project))

    def test_load_descriptor_unparseable_yaml_raises_valueerror(self, temp_project: Path) -> None:
        """Should raise ValueError when YAML is invalid."""
        (temp_project / "margo" / "app.yaml").write_text("kind: [unclosed\n", encoding="utf-8")

        with raises(ValueError, match="not valid YAML"):
            describe_service.load_descriptor(str(temp_project))

    def test_load_descriptor_not_a_mapping_raises_valueerror(self, temp_project: Path) -> None:
        """Should raise ValueError when YAML is not a mapping."""
        (temp_project / "margo" / "app.yaml").write_text(NOT_A_MAPPING_APP_YAML, encoding="utf-8")

        with raises(ValueError, match="must parse into a mapping"):
            describe_service.load_descriptor(str(temp_project))


class TestDescribeServiceTemplatedDescriptor:
    """Tests for load_descriptor with app.yaml.jinja."""

    def test_load_descriptor_template_renders_and_loads(self, temp_project: Path) -> None:
        """Should render app.yaml.jinja with margo.yaml context and load the result."""
        (temp_project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = describe_service.load_descriptor(str(temp_project))

        assert isinstance(result, dict)
        assert result.get("kind") == "ApplicationDescription"
        assert result.get("id") == "hello-world"
        assert result["metadata"]["name"] == "Hello World"

    def test_load_descriptor_unresolved_variable_raises_valueerror(self, temp_project: Path) -> None:
        """Should raise ValueError when Jinja2 variable cannot be resolved."""
        bad_template = TEMPLATED_APP_YAML.replace("{{ manifest.id }}", "{{ manifest.nope }}")
        (temp_project / "margo" / "app.yaml.jinja").write_text(bad_template, encoding="utf-8")

        with raises(ValueError, match="Unresolved Jinja2 variable"):
            describe_service.load_descriptor(str(temp_project))

    def test_load_descriptor_template_cleans_up_temp_file(self, temp_project: Path) -> None:
        """Should clean up the temporary file after rendering and loading."""
        (temp_project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        # Get a reference to temp files before the call
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        before_temps = set(temp_dir.glob("margot-*.yaml"))

        describe_service.load_descriptor(str(temp_project))

        # After the call, any new temp files should be cleaned up
        after_temps = set(temp_dir.glob("margot-*.yaml"))
        assert after_temps == before_temps


class TestDescribeServiceManifestFlag:
    """Tests for load_descriptor with explicit --manifest path."""

    def test_load_descriptor_with_explicit_manifest_path(self, temp_project: Path) -> None:
        """Should load from the explicit --manifest path, bypassing margo.yaml."""
        manifest_path = temp_project / "elsewhere" / "app.yaml"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(VALID_APP_YAML, encoding="utf-8")

        result = describe_service.load_descriptor(str(temp_project), manifest_path=str(manifest_path))

        assert isinstance(result, dict)
        assert result.get("id") == "hello-world"

    def test_load_descriptor_with_missing_manifest_path_raises_valueerror(self, temp_project: Path) -> None:
        """Should raise ValueError when --manifest path does not exist."""
        manifest_path = temp_project / "nope.yaml"

        with raises(ValueError, match="Application description not found"):
            describe_service.load_descriptor(str(temp_project), manifest_path=str(manifest_path))
