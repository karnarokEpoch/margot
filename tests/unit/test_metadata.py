"""Unit tests for domain/metadata.py."""

from pathlib import Path

from pytest import raises

from margot.domain.metadata import (
    ComponentConfig,
    ImageConfig,
    MargoYaml,
    VariantConfig,
    build_jinja2_context,
    load_margo_yaml,
)


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
            id="testapp",
            name="test-app",
            description="Test application",
            version="1.0.0",
            app_version=None,
            annotations={},
            compose=None,
            quadlet=None,
        )
        assert margo_yaml.api_version == "v1"
        assert margo_yaml.name == "test-app"
        assert margo_yaml.description == "Test application"
        assert margo_yaml.annotations == {}
        assert margo_yaml.version == "1.0.0"

    def test_margo_yaml_frozen(self) -> None:
        """Should be immutable after creation."""
        margo_yaml = MargoYaml(
            api_version="v1",
            id="testapp",
            name="test-app",
            description="Test application",
            version="1.0.0",
            app_version=None,
            annotations={},
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
id: testapp
name: test-app
description: A test application
version: 1.0.0
annotations:
  author: test
  version: "1.0"
directory: src/margo
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

        assert result.directory == "src/margo"
        assert result.version == "1.0.0"
        assert result.repository == "private.example.com/margo"

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
id: testapp
name: minimal-app
description: Minimal application
version: 1.0.0
directory: src/margo
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.api_version == "v1"
        assert result.name == "minimal-app"
        assert result.description == "Minimal application"
        assert result.annotations == {}
        assert result.directory == "src/margo"
        assert result.version == "1.0.0"
        assert result.repository is None
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
version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match=r"margo\.yaml missing required field: apiVersion"):
            load_margo_yaml(str(yaml_file))

    def test_missing_name_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when name is missing."""
        yaml_content = """
apiVersion: v1
id: testapp
description: Test application
version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match=r"margo\.yaml missing required field: name"):
            load_margo_yaml(str(yaml_file))

    def test_missing_description_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when description is missing."""
        yaml_content = """
apiVersion: v1
id: testapp
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
id: testapp
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
id: testapp
name: test-app
description: Test application
version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.annotations == {}

    def test_component_no_variants_empty_tuple(self, tmp_path: Path) -> None:
        """Should return empty tuple when component has no variants."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
directory: src/margo
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)
        result = load_margo_yaml(str(yaml_file))

        assert result.directory == "src/margo"

    def test_component_with_variants_tuple(self, tmp_path: Path) -> None:
        """Should return tuple of VariantConfig when component has variants."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
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
id: testapp
name: test-app
description: Test application
version: 1.0.0
annotations:
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.annotations == {}

    def test_component_missing_directory_defaults_to_component_name(self, tmp_path: Path) -> None:
        """Should default an omitted component directory to its component name."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
quadlet:
  version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.quadlet is not None
        assert result.quadlet.directory == "quadlet"

    def test_component_errors_identify_component(self, tmp_path: Path) -> None:
        """Should identify the malformed component in every component parser error."""
        for component_yaml, message in (
            ("compose:\n  variants: invalid\n", r"'compose' variants must be a list"),
            ("quadlet:\n  variants:\n    - invalid\n", r"'quadlet' variant item must be a mapping"),
        ):
            yaml_file = tmp_path / f"{message[:5]}.yaml"
            yaml_file.write_text(
                "apiVersion: v1\nid: testapp\nname: test-app\ndescription: Test application\nversion: 1.0.0\n" + component_yaml
            )

            with raises(ValueError, match=message):
                load_margo_yaml(str(yaml_file))

    def test_variant_missing_name_raises_error(self, tmp_path: Path) -> None:
        """Should raise ValueError when variant is missing name."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
compose:
  directory: compose
  variants:
    - version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        with raises(ValueError, match=r"'compose' variant missing required field 'name'"):
            load_margo_yaml(str(yaml_file))

    def test_variant_missing_version_is_none(self, tmp_path: Path) -> None:
        """Should preserve an omitted variant version for later derivation."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
compose:
  directory: compose
  variants:
    - name: mqtt
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        assert load_margo_yaml(str(yaml_file)).compose.variants[0].version is None  # type: ignore[union-attr]

    def test_multiple_components(self, tmp_path: Path) -> None:
        """Should parse all three optional components when present."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
directory: src/margo
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

        assert result.directory == "src/margo"
        assert result.compose is not None
        assert result.compose.directory == "compose"
        assert result.quadlet is not None
        assert result.quadlet.directory == "quadlet"

    def test_component_with_repository_override(self, tmp_path: Path) -> None:
        """Should parse repository override when provided."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
directory: src/margo
repository: private.example.com/my-margo
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.repository == "private.example.com/my-margo"

    def test_component_repository_none_when_absent(self, tmp_path: Path) -> None:
        """Should have repository=None when not provided."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
directory: src/margo
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        result = load_margo_yaml(str(yaml_file))

        assert result.repository is None

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
id: testapp
name: test-app
description: Test application
version: 1.0.0
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

    def test_load_margo_yaml_with_app_version(self, tmp_path: Path) -> None:
        """Should parse appVersion field into app_version when present."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
appVersion: "1.2.3"
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        meta = load_margo_yaml(str(yaml_file))

        assert meta.app_version == "1.2.3"

    def test_load_margo_yaml_app_version_absent_defaults_to_none(self, tmp_path: Path) -> None:
        """Should set app_version to None when appVersion is absent from margo.yaml."""
        yaml_content = """
apiVersion: v1
id: testapp
name: test-app
description: Test application
version: 1.0.0
"""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(yaml_content)

        meta = load_margo_yaml(str(yaml_file))

        assert meta.app_version is None

    def test_missing_id_raises_error(self, tmp_path: Path) -> None:
        """The stable application id is mandatory."""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text("api" + "Version: v1\nname: test\ndescription: test\nversion: 1.0.0\n")
        with raises(ValueError, match="missing required field: id"):
            load_margo_yaml(str(yaml_file))

    def test_parses_id_and_top_level_version(self, tmp_path: Path) -> None:
        """The template-facing top-level fields retain their declared values."""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text("apiVersion: v1\nid: myapp\nname: test\ndescription: test\nversion: 1.0.0\n")
        meta = load_margo_yaml(str(yaml_file))
        assert meta.id == "myapp"
        assert meta.version == "1.0.0"

    def test_top_level_version_is_required(self, tmp_path: Path) -> None:
        """An omitted top-level margo artifact version is rejected."""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text("apiVersion: v1\nid: myapp\nname: test\ndescription: test\n")
        with raises(ValueError, match="missing required field: version"):
            load_margo_yaml(str(yaml_file))

    def test_reserved_variant_names_raise_error(self, tmp_path: Path) -> None:
        """Names that would overwrite component context keys are rejected."""
        for name in ("version", "component"):
            yaml_file = tmp_path / f"{name}.yaml"
            yaml_file.write_text(
                f"apiVersion: v1\nid: myapp\nname: test\ndescription: test\nversion: 1.0.0\ncompose:\n"
                f"  directory: compose\n  variants:\n    - name: {name}\n      version: 1.0.0\n"
            )
            with raises(ValueError, match=rf"'compose' variant name '{name}' collides with reserved field name"):
                load_margo_yaml(str(yaml_file))

    def test_variant_component_and_image_configuration(self, tmp_path: Path) -> None:
        """Variant component names and image replacement overrides are parsed."""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(
            "apiVersion: v1\nid: myapp\nname: test\ndescription: test\nversion: 1.0.0\ncompose:\n"
            "  directory: compose\n  image:\n    search: app:dev\n    replace: registry/app:<app_tag>\n"
            "  variants:\n    - name: normal\n      version: 1.0.0+gpu\n      component: custom-component\n"
            "      image:\n        search: gpu:dev\n        replace: registry/gpu:<app_tag>\n"
        )
        component = load_margo_yaml(str(yaml_file)).compose
        assert component is not None
        assert component.image == ImageConfig("app:dev", "registry/app:<app_tag>")
        assert component.variants[0].component == "custom-component"
        assert component.variants[0].image == ImageConfig("gpu:dev", "registry/gpu:<app_tag>")

    def test_variant_component_defaults_to_none(self, tmp_path: Path) -> None:
        """Component is optional on a declared variant."""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(
            "apiVersion: v1\nid: myapp\nname: test\ndescription: test\nversion: 1.0.0\ncompose:\n"
            "  directory: compose\n  variants:\n    - name: normal\n      version: 1.0.0\n"
        )
        component = load_margo_yaml(str(yaml_file)).compose
        assert component is not None
        assert component.variants[0].component is None

    def test_image_config_requires_non_empty_search_and_replace(self, tmp_path: Path) -> None:
        """Both component and variant image blocks require usable literal strings."""
        for location, image in (
            ("  image:\n    replace: target\n", "search"),
            ("  image:\n    search: source\n", "replace"),
            ("  image:\n    search: ''\n    replace: target\n", "search"),
            ("  variants:\n    - name: normal\n      version: 1.0.0\n      image:\n        replace: target\n", "search"),
            ("  variants:\n    - name: normal\n      version: 1.0.0\n      image:\n        search: source\n", "replace"),
            (
                "  variants:\n    - name: normal\n      version: 1.0.0\n      image:\n"
                "        search: ''\n        replace: target\n",
                "search",
            ),
        ):
            yaml_file = tmp_path / f"bad-{image}.yaml"
            yaml_file.write_text(
                "apiVersion: v1\nid: myapp\nname: test\ndescription: test\nversion: 1.0.0\ncompose:\n  directory: compose\n"
                + location
            )
            with raises(ValueError, match=f"image {image}"):
                load_margo_yaml(str(yaml_file))

    def test_build_jinja2_context_has_variants_and_direct_access(self) -> None:
        """The context provides uniform flat/variant and direct template access."""
        meta = MargoYaml(
            api_version="v1",
            id="myapp",
            name="display-name",
            description="Test",
            version="1.0.0",
            app_version=None,
            annotations={},
            compose=ComponentConfig(
                "compose",
                None,
                "registry/compose",
                (VariantConfig("gpu", "2.0.0+cuda"),),
            ),
            quadlet=None,
        )
        manifest = build_jinja2_context(meta)["manifest"]
        assert manifest["id"] == "myapp"
        assert manifest["appVersion"] == ""
        assert "margo" not in manifest
        assert manifest["compose"]["variants"][0]["tag"] == "2.0.0_cuda"
        assert manifest["compose"]["gpu"] == manifest["compose"]["variants"][0]
        assert manifest["compose"]["gpu"]["component"] == "myapp-compose-gpu"

    def test_top_level_repository_parsed(self, tmp_path: Path) -> None:
        """Should retain the root repository for component fallback."""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text(
            "apiVersion: v1\nid: myapp\nname: test\ndescription: test\nversion: 1.0.0\n"
            "repository: public.ecr.aws/example/app\nquadlet:\n  directory: quadlet\n"
        )

        meta = load_margo_yaml(str(yaml_file))

        assert meta.repository == "public.ecr.aws/example/app"

    def test_top_level_repository_absent_is_none(self, tmp_path: Path) -> None:
        """Should distinguish an absent root repository from an empty value."""
        yaml_file = tmp_path / "margo.yaml"
        yaml_file.write_text("apiVersion: v1\nid: myapp\nname: test\ndescription: test\nversion: 1.0.0\n")

        meta = load_margo_yaml(str(yaml_file))

        assert meta.repository is None

    def test_build_jinja2_context_uses_global_repository_for_component(self) -> None:
        """Should use the global repository when a component has no override."""
        meta = MargoYaml(
            api_version="v1",
            id="myapp",
            name="test",
            description="Test",
            version="1.0.0",
            app_version=None,
            annotations={},
            compose=None,
            quadlet=ComponentConfig("quadlet", "1.0.0", None, ()),
        )

        manifest = build_jinja2_context(meta, global_repository="public.ecr.aws/example/app")["manifest"]

        assert manifest["quadlet"]["repository"] == "public.ecr.aws/example/app"

    def test_build_jinja2_context_component_repository_overrides_global(self) -> None:
        """Should prefer a component repository over the global fallback."""
        meta = MargoYaml(
            api_version="v1",
            id="myapp",
            name="test",
            description="Test",
            version="1.0.0",
            app_version=None,
            annotations={},
            compose=None,
            quadlet=ComponentConfig("quadlet", "1.0.0", "public.ecr.aws/example/quadlet", ()),
        )

        manifest = build_jinja2_context(meta, global_repository="public.ecr.aws/example/app")["manifest"]

        assert manifest["quadlet"]["repository"] == "public.ecr.aws/example/quadlet"


class TestRedesignedJinjaContext:
    """Tests for the top-level margo metadata and derived component context."""

    def test_manifest_has_top_level_directory_and_repository(self) -> None:
        """Top-level margo source metadata is exposed to templates."""
        meta = MargoYaml(
            api_version="v1",
            id="myapp",
            name="test",
            description="Test",
            version="1.0.0",
            app_version=None,
            annotations={},
            compose=None,
            quadlet=None,
            directory="app-source",
            repository="public.ecr.aws/g2n4p2m7/margo",
        )

        manifest = build_jinja2_context(meta)["manifest"]

        assert manifest["directory"] == "app-source"
        assert manifest["repository"] == "public.ecr.aws/g2n4p2m7/margo"
        assert "margo" not in manifest

    def test_flat_component_context_exposes_direct_fields(self) -> None:
        """Flat component values are available without indexing the synthetic variant."""
        meta = MargoYaml(
            api_version="v1",
            id="myapp",
            name="test",
            description="Test",
            version="1.0.0",
            app_version=None,
            annotations={},
            compose=ComponentConfig("compose", "2.0.0+build", "registry/example", ()),
            quadlet=None,
        )

        component = build_jinja2_context(meta)["manifest"]["compose"]

        assert component["component"] == "myapp-compose"
        assert component["tag"] == "2.0.0_build"
        assert component["ref"] == "registry/example:2.0.0_build"
        assert component["variants"][0]["component"] == "myapp-compose"

    def test_absent_variant_version_is_derived_in_context(self) -> None:
        """Variant version derivation happens while creating the template context."""
        meta = MargoYaml(
            api_version="v1",
            id="myapp",
            name="test",
            description="Test",
            version="1.0.0",
            app_version=None,
            annotations={},
            compose=ComponentConfig("compose", "2.1.0", "registry/example", (VariantConfig("default"),)),
            quadlet=None,
        )

        variant = build_jinja2_context(meta)["manifest"]["compose"]["variants"][0]

        assert variant["version"] == "2.1.0+compose-default"
        assert variant["tag"] == "2.1.0_compose-default"
