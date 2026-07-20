"""Unit tests for domain/metadata.py."""

from pathlib import Path

from pytest import raises

from margot.domain.metadata import ComponentConfig, MargoYaml, VariantConfig, load_margo_yaml


class TestVariantConfig:
    """Tests for VariantConfig dataclass."""

    def test_variant_config_creation(self) -> None:
        """Should create VariantConfig with name and version."""
        variant = VariantConfig(name="mqtt", version="1.0.0")
        assert variant.name == "mqtt"
        assert variant.version == "1.0.0"

    def test_variant_config_frozen(self) -> None:
        """Should be immutable after creation."""
        variant = VariantConfig(name="mqtt", version="1.0.0")
        with raises(AttributeError):
            variant.name = "other"  # type: ignore[attr-defined]


class TestComponentConfig:
    """Tests for ComponentConfig dataclass."""

    def test_component_config_minimal(self) -> None:
        """Should create ComponentConfig with directory and empty variants."""
        component = ComponentConfig(directory="src/margo", version=None, repository=None, variants=())
        assert component.directory == "src/margo"
        assert component.version is None
        assert component.repository is None
        assert component.variants == ()

    def test_component_config_with_version(self) -> None:
        """Should include version when provided."""
        component = ComponentConfig(directory="src/margo", version="1.2.3", repository=None, variants=())
        assert component.version == "1.2.3"

    def test_component_config_with_repository(self) -> None:
        """Should include repository override when provided."""
        component = ComponentConfig(
            directory="src/margo",
            version="1.2.3",
            repository="private.example.com/margo",
            variants=(),
        )
        assert component.repository == "private.example.com/margo"

    def test_component_config_with_variants(self) -> None:
        """Should store variants as immutable tuple."""
        variant1 = VariantConfig(name="mqtt", version="1.0.0")
        variant2 = VariantConfig(name="influx", version="2.0.0")
        component = ComponentConfig(
            directory="src/compose",
            version=None,
            repository=None,
            variants=(variant1, variant2),
        )
        assert len(component.variants) == 2
        assert component.variants[0].name == "mqtt"
        assert component.variants[1].name == "influx"

    def test_component_config_frozen(self) -> None:
        """Should be immutable after creation."""
        component = ComponentConfig(directory="src/margo", version=None, repository=None, variants=())
        with raises(AttributeError):
            component.directory = "other"  # type: ignore[attr-defined]


class TestMargoYaml:
    """Tests for MargoYaml dataclass."""

    def test_margo_yaml_minimal(self) -> None:
        """Should create MargoYaml with required fields and empty annotations."""
        margo_yaml = MargoYaml(
            api_version="v1",
            name="test-app",
            description="Test application",
            annotations={},
            margo=None,
            compose=None,
            quadlet=None,
        )
        assert margo_yaml.api_version == "v1"
        assert margo_yaml.name == "test-app"
        assert margo_yaml.description == "Test application"
        assert margo_yaml.annotations == {}
        assert margo_yaml.margo is None

    def test_margo_yaml_frozen(self) -> None:
        """Should be immutable after creation."""
        margo_yaml = MargoYaml(
            api_version="v1",
            name="test-app",
            description="Test application",
            annotations={},
            margo=None,
            compose=None,
            quadlet=None,
        )
        with raises(AttributeError):
            margo_yaml.name = "other"  # type: ignore[attr-defined]


class TestLoadMargoYaml:
    """Tests for load_margo_yaml() parser."""

    def test_parse_fully_populated_yaml(self, tmp_path: Path) -> None:
        """Should parse a fully populated margo.yaml with all components, variants, and annotations."""
        yaml_content = """
apiVersion: v1
name: test-app
description: A test application
annotations:
  author: test
  version: "1.0"
margo:
  directory: src/margo
  version: 1.0.0
  repository: private.example.com/margo
compose:
  directory: compose
  variants:
    - name: mqtt
      version: 1.0.0_addon-mosquitto
    - name: influx
      version: 2.0.0
quadlet:
  directory: quadlet
  version: 3.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.api_version == "v1"
        assert result.name == "test-app"
        assert result.description == "A test application"
        assert result.annotations == {"author": "test", "version": "1.0"}

        assert result.margo is not None
        assert result.margo.directory == "src/margo"
        assert result.margo.version == "1.0.0"
        assert result.margo.repository == "private.example.com/margo"
        assert result.margo.variants == ()

        assert result.compose is not None
        assert result.compose.directory == "compose"
        assert result.compose.version is None
        assert len(result.compose.variants) == 2
        assert result.compose.variants[0].name == "mqtt"
        assert result.compose.variants[0].version == "1.0.0_addon-mosquitto"
        assert result.compose.variants[1].name == "influx"
        assert result.compose.variants[1].version == "2.0.0"

        assert result.quadlet is not None
        assert result.quadlet.directory == "quadlet"
        assert result.quadlet.version == "3.0.0"
        assert result.quadlet.variants == ()

    def test_parse_minimal_valid_yaml(self, tmp_path: Path) -> None:
        """Should parse minimal valid yaml with only required fields and one component."""
        yaml_content = """
apiVersion: v1
name: minimal-app
description: Minimal application
margo:
  directory: src/margo
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.api_version == "v1"
        assert result.name == "minimal-app"
        assert result.description == "Minimal application"
        assert result.annotations == {}
        assert result.margo is not None
        assert result.margo.directory == "src/margo"
        assert result.margo.version is None
        assert result.margo.repository is None
        assert result.margo.variants == ()
        assert result.compose is None
        assert result.quadlet is None

    def test_file_not_found_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when file is not found."""
        yaml_file = tmp_path / "nonexistent.yaml"
        with raises(ValueError, match=r"margo\.yaml not found"):
            load_margo_yaml(str(yaml_file))

    def test_missing_apiversion_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when apiVersion is missing."""
        yaml_content = """
name: test-app
description: Test application
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match=r"margo\.yaml missing required field: apiVersion"):
            load_margo_yaml(str(yaml_file))

    def test_missing_name_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when name is missing."""
        yaml_content = """
apiVersion: v1
description: Test application
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match=r"margo\.yaml missing required field: name"):
            load_margo_yaml(str(yaml_file))

    def test_missing_description_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when description is missing."""
        yaml_content = """
apiVersion: v1
name: test-app
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match=r"margo\.yaml missing required field: description"):
            load_margo_yaml(str(yaml_file))

    def test_invalid_yaml_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when YAML is malformed."""
        yaml_content = """
apiVersion: v1
name: test-app
  invalid: indent:
    broken yaml
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match=r"margo\.yaml is not valid YAML:"):
            load_margo_yaml(str(yaml_file))

    def test_annotations_absent_returns_empty_dict(self, tmp_path: Path) -> None:
        """Should return empty dict when annotations are absent."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.annotations == {}

    def test_component_no_variants_empty_tuple(self, tmp_path: Path) -> None:
        """Should return empty tuple when component has no variants."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
margo:
  directory: src/margo
  version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.margo is not None
        assert result.margo.variants == ()

    def test_component_with_variants_tuple(self, tmp_path: Path) -> None:
        """Should return tuple of VariantConfig when component has variants."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
compose:
  directory: compose
  variants:
    - name: mqtt
      version: 1.0.0
    - name: influx
      version: 2.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.compose is not None
        assert isinstance(result.compose.variants, tuple)
        assert len(result.compose.variants) == 2
        assert result.compose.variants[0].name == "mqtt"
        assert result.compose.variants[0].version == "1.0.0"

    def test_annotations_null_becomes_empty_dict(self, tmp_path: Path) -> None:
        """Should convert null annotations to empty dict."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
annotations:
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.annotations == {}

    def test_component_missing_directory_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when component is missing directory."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
margo:
  version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match="component missing required field 'directory'"):
            load_margo_yaml(str(yaml_file))

    def test_variant_missing_name_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when variant is missing name."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
compose:
  directory: compose
  variants:
    - version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match="variant missing required field 'name' or 'version'"):
            load_margo_yaml(str(yaml_file))

    def test_variant_missing_version_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when variant is missing version."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
compose:
  directory: compose
  variants:
    - name: mqtt
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match="variant missing required field 'name' or 'version'"):
            load_margo_yaml(str(yaml_file))

    def test_multiple_components(self, tmp_path: Path) -> None:
        """Should parse all three optional components when present."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
margo:
  directory: src/margo
  version: 1.0.0
compose:
  directory: compose
  version: 2.0.0
quadlet:
  directory: quadlet
  version: 3.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.margo is not None
        assert result.margo.directory == "src/margo"
        assert result.compose is not None
        assert result.compose.directory == "compose"
        assert result.quadlet is not None
        assert result.quadlet.directory == "quadlet"

    def test_component_with_repository_override(self, tmp_path: Path) -> None:
        """Should parse repository override when provided."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
margo:
  directory: src/margo
  version: 1.0.0
  repository: private.example.com/my-margo
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.margo is not None
        assert result.margo.repository == "private.example.com/my-margo"

    def test_component_repository_none_when_absent(self, tmp_path: Path) -> None:
        """Should have repository=None when not provided."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
margo:
  directory: src/margo
  version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.margo is not None
        assert result.margo.repository is None

    def test_empty_yaml_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when YAML is empty or only whitespace."""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text("   \n  \n")

        with raises(ValueError, match=r"margo\.yaml is not valid YAML: expected mapping at root"):
            load_margo_yaml(str(yaml_file))

    def test_variant_with_underscore_in_version(self, tmp_path: Path) -> None:
        """Should preserve underscores in variant version strings."""
        yaml_content = """
apiVersion: v1
name: test-app
description: Test application
compose:
  directory: compose
  variants:
    - name: addon
      version: 1.0.0_addon-mosquitto
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.compose is not None
        assert result.compose.variants[0].version == "1.0.0_addon-mosquitto"
