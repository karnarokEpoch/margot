"""Unit tests for the describe domain model — identity, catalog, and deployment profiles."""


from margot.domain.describe import (
    Configuration,
    ConfigurationSection,
    Parameter,
    ParameterTarget,
    Schema,
    Setting,
    build_catalog,
    build_component_first,
    build_configuration,
    build_deployment_profiles,
    build_identity,
    component_index,
    unreferenced_parameters,
)
from margot.domain.metadata import MargoYaml


class TestIdentityModel:
    """Tests for Identity dataclass and build_identity."""

    def test_build_identity_minimal(self) -> None:
        """Should extract identity fields from a minimal descriptor."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
            "metadata": {
                "name": "Hello World",
                "version": "1.0.0",
            },
        }

        identity = build_identity(doc)

        assert identity.id == "hello-world"
        assert identity.api_version == "application.margo.org/v1alpha1"
        assert identity.kind == "ApplicationDescription"
        assert identity.name == "Hello World"
        assert identity.version == "1.0.0"
        assert identity.description is None

    def test_build_identity_with_description(self) -> None:
        """Should include optional description field."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
            "metadata": {
                "name": "Hello World",
                "version": "1.0.0",
                "description": "A sample application",
            },
        }

        identity = build_identity(doc)

        assert identity.description == "A sample application"

    def test_build_identity_empty_description_preserved(self) -> None:
        """Should distinguish absent description from empty string."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
            "metadata": {
                "name": "Hello World",
                "version": "1.0.0",
                "description": "",
            },
        }

        identity = build_identity(doc)

        assert identity.description == ""

    def test_build_identity_missing_metadata(self) -> None:
        """Should handle missing metadata gracefully."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
        }

        identity = build_identity(doc)

        assert identity.name is None
        assert identity.version is None

    def test_build_identity_oci_uri_with_repository_no_plus(self) -> None:
        """Should compute oci_uri from meta with non-empty repository and version without +."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
            "metadata": {
                "name": "Hello World",
                "version": "1.0.0",
            },
        }
        meta = MargoYaml(
            api_version="v1",
            id="hello-world",
            name="Hello World",
            description="Test",
            app_version=None,
            version="1.0.0",
            annotations={},
            compose=None,
            quadlet=None,
            repository="public.ecr.aws/g2n4p2m7/margo",
        )

        identity = build_identity(doc, meta)

        assert identity.oci_uri == "public.ecr.aws/g2n4p2m7/margo:1.0.0"

    def test_build_identity_oci_uri_with_plus_replaced_by_underscore(self) -> None:
        """Should replace + with _ in version when computing oci_uri."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
            "metadata": {
                "name": "Hello World",
                "version": "1.0.0+compose-default",
            },
        }
        meta = MargoYaml(
            api_version="v1",
            id="hello-world",
            name="Hello World",
            description="Test",
            app_version=None,
            version="1.0.0+compose-default",
            annotations={},
            compose=None,
            quadlet=None,
            repository="public.ecr.aws/org/app",
        )

        identity = build_identity(doc, meta)

        assert identity.oci_uri == "public.ecr.aws/org/app:1.0.0_compose-default"

    def test_build_identity_oci_uri_none_when_meta_none(self) -> None:
        """Should set oci_uri to None when meta is None."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
            "metadata": {
                "name": "Hello World",
                "version": "1.0.0",
            },
        }

        identity = build_identity(doc, meta=None)

        assert identity.oci_uri is None

    def test_build_identity_oci_uri_none_when_repository_none(self) -> None:
        """Should set oci_uri to None when meta.repository is None."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
            "metadata": {
                "name": "Hello World",
                "version": "1.0.0",
            },
        }
        meta = MargoYaml(
            api_version="v1",
            id="hello-world",
            name="Hello World",
            description="Test",
            app_version=None,
            version="1.0.0",
            annotations={},
            compose=None,
            quadlet=None,
            repository=None,
        )

        identity = build_identity(doc, meta)

        assert identity.oci_uri is None

    def test_build_identity_oci_uri_none_when_repository_empty_string(self) -> None:
        """Should set oci_uri to None when meta.repository is an empty string."""
        doc = {
            "id": "hello-world",
            "apiVersion": "application.margo.org/v1alpha1",
            "kind": "ApplicationDescription",
            "metadata": {
                "name": "Hello World",
                "version": "1.0.0",
            },
        }
        meta = MargoYaml(
            api_version="v1",
            id="hello-world",
            name="Hello World",
            description="Test",
            app_version=None,
            version="1.0.0",
            annotations={},
            compose=None,
            quadlet=None,
            repository="",
        )

        identity = build_identity(doc, meta)

        assert identity.oci_uri is None


class TestCatalogModel:
    """Tests for Catalog dataclass and build_catalog."""

    def test_build_catalog_absent_returns_none(self) -> None:
        """Should return None when metadata.catalog is absent."""
        doc = {"metadata": {}}

        catalog = build_catalog(doc)

        assert catalog is None

    def test_build_catalog_empty_returns_none(self) -> None:
        """Should return None when metadata.catalog is an empty mapping."""
        doc = {"metadata": {"catalog": {}}}

        catalog = build_catalog(doc)

        assert catalog is None

    def test_build_catalog_application_only(self) -> None:
        """Should extract catalog.application fields."""
        doc = {
            "metadata": {
                "catalog": {
                    "application": {
                        "tagline": "Simple monitoring",
                        "site": "https://example.com",
                        "icon": "icon.png",
                        "descriptionFile": "README.md",
                        "licenseFile": "LICENSE",
                        "releaseNotes": "NOTES.md",
                        "tags": ["iot", "monitoring"],
                    }
                }
            }
        }

        catalog = build_catalog(doc)

        assert catalog is not None
        assert catalog.application is not None
        assert catalog.application.tagline == "Simple monitoring"
        assert catalog.application.site == "https://example.com"
        assert catalog.application.tags == ["iot", "monitoring"]

    def test_build_catalog_application_partial_fields(self) -> None:
        """Should handle partial application fields."""
        doc = {
            "metadata": {
                "catalog": {
                    "application": {
                        "tagline": "Simple monitoring",
                    }
                }
            }
        }

        catalog = build_catalog(doc)

        assert catalog is not None
        assert catalog.application.tagline == "Simple monitoring"
        assert catalog.application.site is None

    def test_build_catalog_author_list(self) -> None:
        """Should extract catalog.author array."""
        doc = {
            "metadata": {
                "catalog": {
                    "author": [
                        {"name": "Jane Doe", "email": "jane@example.com"},
                        {"name": "John Smith"},
                    ]
                }
            }
        }

        catalog = build_catalog(doc)

        assert catalog is not None
        assert len(catalog.author) == 2
        assert catalog.author[0].name == "Jane Doe"
        assert catalog.author[0].email == "jane@example.com"
        assert catalog.author[1].email is None

    def test_build_catalog_organization_list(self) -> None:
        """Should extract catalog.organization array."""
        doc = {
            "metadata": {
                "catalog": {
                    "organization": [
                        {"name": "Acme Corp", "site": "https://acme.com"},
                        {"name": "Widgets Inc"},
                    ]
                }
            }
        }

        catalog = build_catalog(doc)

        assert catalog is not None
        assert len(catalog.organization) == 2
        assert catalog.organization[0].name == "Acme Corp"
        assert catalog.organization[1].site is None


class TestDeploymentProfilesModel:
    """Tests for DeploymentProfile, Component, and build_deployment_profiles."""

    def test_build_deployment_profiles_empty(self) -> None:
        """Should return empty list when deploymentProfiles is absent."""
        doc = {}

        profiles = build_deployment_profiles(doc)

        assert profiles == []

    def test_build_deployment_profiles_single(self) -> None:
        """Should extract a single deployment profile."""
        doc = {
            "deploymentProfiles": [
                {
                    "type": "compose",
                    "id": "default",
                    "description": "Compose deployment",
                    "components": [
                        {"name": "app-compose", "properties": {"repository": "oci://..."}},
                    ],
                }
            ]
        }

        profiles = build_deployment_profiles(doc)

        assert len(profiles) == 1
        assert profiles[0].type == "compose"
        assert profiles[0].id == "default"
        assert profiles[0].description == "Compose deployment"
        assert len(profiles[0].components) == 1

    def test_build_deployment_profiles_component_properties_preserved(self) -> None:
        """Should preserve all component property keys and values."""
        doc = {
            "deploymentProfiles": [
                {
                    "type": "helm",
                    "id": "k8s",
                    "components": [
                        {
                            "name": "app-helm",
                            "properties": {
                                "repository": "oci://helm.example.com/app",
                                "revision": "1.0.0",
                                "timeout": "5m0s",
                                "custom-key": "custom-value",
                            },
                        },
                    ],
                }
            ]
        }

        profiles = build_deployment_profiles(doc)

        component = profiles[0].components[0]
        assert component.properties.get("repository") == "oci://helm.example.com/app"
        assert component.properties.get("custom-key") == "custom-value"

    def test_build_deployment_profiles_component_without_repository(self) -> None:
        """Should handle component without repository key."""
        doc = {
            "deploymentProfiles": [
                {
                    "type": "compose",
                    "id": "default",
                    "components": [
                        {"name": "app-compose", "properties": {}},
                    ],
                }
            ]
        }

        profiles = build_deployment_profiles(doc)

        component = profiles[0].components[0]
        assert component.name == "app-compose"
        assert component.properties == {}

    def test_build_deployment_profiles_empty_components(self) -> None:
        """Should handle profile with zero components."""
        doc = {
            "deploymentProfiles": [
                {
                    "type": "quadlet",
                    "id": "systemd",
                    "components": [],
                }
            ]
        }

        profiles = build_deployment_profiles(doc)

        assert profiles[0].components == []

    def test_build_deployment_profiles_no_components_field(self) -> None:
        """Should handle profile with missing components field."""
        doc = {
            "deploymentProfiles": [
                {
                    "type": "compose",
                    "id": "default",
                }
            ]
        }

        profiles = build_deployment_profiles(doc)

        assert profiles[0].components == []


class TestComponentIndex:
    """Tests for the component_index function."""

    def test_component_index_empty(self) -> None:
        """Should return empty list when no profiles."""
        doc = {}

        index = component_index(doc)

        assert index == []

    def test_component_index_deduplication(self) -> None:
        """Should deduplicate component names across profiles."""
        doc = {
            "deploymentProfiles": [
                {
                    "type": "compose",
                    "id": "default",
                    "components": [
                        {"name": "app-compose"},
                        {"name": "broker"},
                    ],
                },
                {
                    "type": "compose",
                    "id": "modular",
                    "components": [
                        {"name": "app-compose"},  # duplicate
                        {"name": "daemon"},
                    ],
                },
            ]
        }

        index = component_index(doc)

        assert index == ["app-compose", "broker", "daemon"]

    def test_component_index_first_seen_order(self) -> None:
        """Should preserve first-seen-order, not alphabetical."""
        doc = {
            "deploymentProfiles": [
                {
                    "type": "compose",
                    "id": "default",
                    "components": [
                        {"name": "zebra"},
                        {"name": "alpha"},
                    ],
                },
            ]
        }

        index = component_index(doc)

        assert index == ["zebra", "alpha"]

    def test_component_index_from_all_profiles(self) -> None:
        """Should traverse all profiles to collect all component names."""
        doc = {
            "deploymentProfiles": [
                {"type": "compose", "id": "default", "components": [{"name": "app1"}]},
                {"type": "helm", "id": "k8s", "components": [{"name": "app2"}]},
                {"type": "quadlet", "id": "systemd", "components": [{"name": "app3"}]},
            ]
        }

        index = component_index(doc)

        assert index == ["app1", "app2", "app3"]


class TestConfigurationModel:
    """Tests for Configuration, Setting, Schema, Parameter and build_configuration."""

    def test_build_configuration_empty(self) -> None:
        """Should return empty Configuration when no configuration block."""
        doc = {}

        config = build_configuration(doc)

        assert config.sections == []
        assert config.unreferenced == []

    def test_build_configuration_empty_sections(self) -> None:
        """Should return Configuration with empty sections list when sections absent."""
        doc = {"configuration": {}}

        config = build_configuration(doc)

        assert config.sections == []

    def test_build_configuration_section_with_settings(self) -> None:
        """Should extract section and its settings."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "MQTT",
                        "settings": [
                            {
                                "parameter": "mqttBroker",
                                "name": "Broker",
                                "description": "MQTT broker host",
                                "immutable": False,
                                "schema": "mqttBrokerSchema",
                            }
                        ],
                    }
                ],
                "schema": [
                    {
                        "name": "mqttBrokerSchema",
                        "dataType": "string",
                        "minLength": 1,
                        "maxLength": 255,
                    }
                ],
            },
            "parameters": {
                "mqttBroker": {
                    "value": "localhost",
                    "targets": [
                        {
                            "pointer": "mqtt.broker",
                            "components": ["app-compose"],
                        }
                    ],
                }
            },
        }

        config = build_configuration(doc)

        assert len(config.sections) == 1
        section = config.sections[0]
        assert section.name == "MQTT"
        assert len(section.settings) == 1
        setting = section.settings[0]
        assert setting.parameter == "mqttBroker"
        assert setting.name == "Broker"
        assert setting.immutable is False

    def test_build_configuration_setting_with_schema_lookup(self) -> None:
        """Should resolve schema reference from configuration.schema[]."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "Settings",
                        "settings": [
                            {
                                "parameter": "param1",
                                "name": "Param",
                                "schema": "schema1",
                            }
                        ],
                    }
                ],
                "schema": [
                    {
                        "name": "schema1",
                        "dataType": "string",
                        "minLength": 5,
                    }
                ],
            },
            "parameters": {"param1": {"value": "test"}},
        }

        config = build_configuration(doc)

        setting = config.sections[0].settings[0]
        assert setting.schema is not None
        assert setting.schema.data_type == "string"
        assert setting.schema.min_length == 5

    def test_build_configuration_setting_references_missing_schema(self) -> None:
        """Should set schema to None when referenced schema is not defined."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "Settings",
                        "settings": [
                            {
                                "parameter": "param1",
                                "name": "Param",
                                "schema": "missing",
                            }
                        ],
                    }
                ],
                "schema": [],
            },
            "parameters": {"param1": {"value": "test"}},
        }

        config = build_configuration(doc)

        setting = config.sections[0].settings[0]
        assert setting.schema is None

    def test_build_configuration_setting_references_missing_parameter(self) -> None:
        """Should store parameter name and set parameter_resolved to None when not found."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "Settings",
                        "settings": [
                            {
                                "parameter": "missing",
                                "name": "Param",
                                "schema": "schema1",
                            }
                        ],
                    }
                ],
                "schema": [
                    {
                        "name": "schema1",
                        "dataType": "string",
                    }
                ],
            },
            "parameters": {},
        }

        config = build_configuration(doc)

        setting = config.sections[0].settings[0]
        assert setting.parameter == "missing"
        assert setting.parameter_resolved is None

    def test_build_configuration_setting_immutable_tag(self) -> None:
        """Should preserve immutable flag."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "Settings",
                        "settings": [
                            {
                                "parameter": "param1",
                                "name": "Immutable Param",
                                "immutable": True,
                                "schema": "schema1",
                            }
                        ],
                    }
                ],
                "schema": [{"name": "schema1", "dataType": "string"}],
            },
            "parameters": {"param1": {"value": "test"}},
        }

        config = build_configuration(doc)

        setting = config.sections[0].settings[0]
        assert setting.immutable is True

    def test_build_configuration_parameter_targets_with_components(self) -> None:
        """Should extract parameter targets and their component lists."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "Settings",
                        "settings": [
                            {
                                "parameter": "param1",
                                "name": "Param",
                                "schema": "schema1",
                            }
                        ],
                    }
                ],
                "schema": [{"name": "schema1", "dataType": "string"}],
            },
            "parameters": {
                "param1": {
                    "value": "default",
                    "targets": [
                        {
                            "pointer": "path.to.setting",
                            "components": ["app1", "app2"],
                        },
                        {
                            "pointer": "another.path",
                            "components": ["app3"],
                        },
                    ],
                }
            },
        }

        config = build_configuration(doc)

        setting = config.sections[0].settings[0]
        param = setting.parameter_resolved
        assert param is not None
        assert len(param.targets) == 2
        assert param.targets[0].pointer == "path.to.setting"
        assert param.targets[0].components == ["app1", "app2"]

    def test_build_configuration_target_with_undeclared_component(self) -> None:
        """Should include undeclared components in target.components, marked in the display layer."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "Settings",
                        "settings": [
                            {
                                "parameter": "param1",
                                "name": "Param",
                                "schema": "schema1",
                            }
                        ],
                    }
                ],
                "schema": [{"name": "schema1", "dataType": "string"}],
            },
            "parameters": {
                "param1": {
                    "value": "default",
                    "targets": [
                        {
                            "pointer": "path",
                            "components": ["app1", "undeclared-app"],
                        }
                    ],
                }
            },
        }

        config = build_configuration(doc)

        param = config.sections[0].settings[0].parameter_resolved
        assert param is not None
        target = param.targets[0]
        # The data model just stores the components as they are; marking as "not declared"
        # happens in the display layer
        assert "undeclared-app" in target.components

    def test_build_configuration_unreferenced_parameters(self) -> None:
        """Should compute list of parameters not referenced by any setting."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "Settings",
                        "settings": [
                            {
                                "parameter": "referenced",
                                "name": "Referenced",
                                "schema": "schema1",
                            }
                        ],
                    }
                ],
                "schema": [{"name": "schema1", "dataType": "string"}],
            },
            "parameters": {
                "referenced": {"value": "ref"},
                "orphan1": {"value": "orphan"},
                "orphan2": {"value": "orphan"},
            },
        }

        config = build_configuration(doc)

        assert set(config.unreferenced) == {"orphan1", "orphan2"}

    def test_build_configuration_no_unreferenced_parameters(self) -> None:
        """Should return empty unreferenced list when all parameters are referenced."""
        doc = {
            "configuration": {
                "sections": [
                    {
                        "name": "Settings",
                        "settings": [
                            {
                                "parameter": "param1",
                                "name": "Param1",
                                "schema": "schema1",
                            },
                            {
                                "parameter": "param2",
                                "name": "Param2",
                                "schema": "schema1",
                            },
                        ],
                    }
                ],
                "schema": [{"name": "schema1", "dataType": "string"}],
            },
            "parameters": {
                "param1": {"value": "a"},
                "param2": {"value": "b"},
            },
        }

        config = build_configuration(doc)

        assert config.unreferenced == []

    def test_constraint_formatting_range(self) -> None:
        """Should format minValue/maxValue range."""
        schema = Schema(
            name="test",
            data_type="integer",
            min_value=1,
            max_value=65535,
        )

        assert schema.min_value == 1
        assert schema.max_value == 65535

    def test_constraint_formatting_min_length_max_length(self) -> None:
        """Should format string length constraints."""
        schema = Schema(
            name="test",
            data_type="string",
            min_length=5,
            max_length=100,
        )

        assert schema.min_length == 5
        assert schema.max_length == 100

    def test_constraint_formatting_regex(self) -> None:
        """Should capture regex pattern."""
        schema = Schema(
            name="test",
            data_type="string",
            regex_match=r"^[a-z]+$",
        )

        assert schema.regex_match == r"^[a-z]+$"

    def test_constraint_formatting_options(self) -> None:
        """Should preserve options list."""
        schema = Schema(
            name="test",
            data_type="string",
            options=["a", "b", "c"],
        )

        assert schema.options == ["a", "b", "c"]

    def test_constraint_formatting_multiselect(self) -> None:
        """Should preserve multiselect flag."""
        schema = Schema(
            name="test",
            data_type="string",
            multiselect=True,
        )

        assert schema.multiselect is True

    def test_constraint_formatting_allow_empty(self) -> None:
        """Should preserve allowEmpty flag."""
        schema = Schema(
            name="test",
            data_type="string",
            allow_empty=True,
        )

        assert schema.allow_empty is True


class TestComponentFirstView:
    """Tests for build_component_first function."""

    def test_component_first_basic_structure(self) -> None:
        """Should build a component-first view with per-component parameter edges."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Settings",
                    settings=[
                        Setting(
                            parameter="param1",
                            name="Param 1",
                            description="Test",
                            immutable=False,
                            schema=Schema(name="schema1", data_type="string"),
                            parameter_resolved=Parameter(
                                value="default1",
                                targets=[
                                    ParameterTarget(
                                        pointer="path.to.param1",
                                        components=["comp-a", "comp-b"],
                                    )
                                ],
                            ),
                        )
                    ],
                )
            ],
            unreferenced=[],
        )
        index = ["comp-a", "comp-b"]

        view = build_component_first(config, index)

        assert view is not None
        assert len(view.components) == 2
        # Find comp-a
        comp_a = next((c for c in view.components if c.name == "comp-a"), None)
        assert comp_a is not None
        assert len(comp_a.parameters) == 1
        assert comp_a.parameters[0].parameter_name == "param1"

    def test_component_first_empty_components(self) -> None:
        """Should include components with no parameters."""
        config = Configuration(sections=[], unreferenced=[])
        index = ["comp-a", "comp-b"]

        view = build_component_first(config, index)

        assert len(view.components) == 2
        # Each component should have empty parameters list
        for comp in view.components:
            assert comp.parameters == []

    def test_component_first_multiple_targets_same_component(self) -> None:
        """Should aggregate multiple targets targeting the same component."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Settings",
                    settings=[
                        Setting(
                            parameter="param1",
                            name="Param 1",
                            immutable=False,
                            schema=Schema(name="schema1", data_type="string"),
                            parameter_resolved=Parameter(
                                value="default1",
                                targets=[
                                    ParameterTarget(
                                        pointer="path1",
                                        components=["comp-a"],
                                    ),
                                    ParameterTarget(
                                        pointer="path2",
                                        components=["comp-a"],
                                    ),
                                ],
                            ),
                        )
                    ],
                )
            ],
            unreferenced=[],
        )
        index = ["comp-a"]

        view = build_component_first(config, index)

        comp_a = view.components[0]
        # Both targets should be included
        assert len(comp_a.parameters) == 2

    def test_component_first_ordering_matches_component_index(self) -> None:
        """Should order components by the component_index order."""
        config = Configuration(sections=[], unreferenced=[])
        index = ["zebra", "apple", "banana"]

        view = build_component_first(config, index)

        assert [c.name for c in view.components] == ["zebra", "apple", "banana"]

    def test_component_first_setting_ordering_preserved(self) -> None:
        """Should preserve setting/section order in parameter edges."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Section A",
                    settings=[
                        Setting(
                            parameter="param1",
                            name="Param 1",
                            immutable=False,
                            schema=Schema(name="schema1", data_type="string"),
                            parameter_resolved=Parameter(
                                value="v1",
                                targets=[ParameterTarget(pointer="p1", components=["comp-a"])],
                            ),
                        ),
                        Setting(
                            parameter="param2",
                            name="Param 2",
                            immutable=False,
                            schema=Schema(name="schema2", data_type="integer"),
                            parameter_resolved=Parameter(
                                value=42,
                                targets=[ParameterTarget(pointer="p2", components=["comp-a"])],
                            ),
                        ),
                    ],
                ),
                ConfigurationSection(
                    name="Section B",
                    settings=[
                        Setting(
                            parameter="param3",
                            name="Param 3",
                            immutable=False,
                            schema=Schema(name="schema3", data_type="boolean"),
                            parameter_resolved=Parameter(
                                value=True,
                                targets=[ParameterTarget(pointer="p3", components=["comp-a"])],
                            ),
                        ),
                    ],
                ),
            ],
            unreferenced=[],
        )
        index = ["comp-a"]

        view = build_component_first(config, index)

        comp_a = view.components[0]
        # Parameters should be in declaration order: param1, param2, param3
        assert [p.parameter_name for p in comp_a.parameters] == [
            "param1",
            "param2",
            "param3",
        ]

    def test_component_first_parameter_details_preserved(self) -> None:
        """Should preserve parameter details in the view."""
        schema = Schema(
            name="testSchema",
            data_type="string",
            min_length=1,
            max_length=100,
        )
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Settings",
                    settings=[
                        Setting(
                            parameter="testParam",
                            name="Test Parameter",
                            description="A test parameter",
                            immutable=True,
                            schema=schema,
                            parameter_resolved=Parameter(
                                value="test-value",
                                targets=[
                                    ParameterTarget(
                                        pointer="config.test",
                                        components=["comp-a"],
                                    )
                                ],
                            ),
                        )
                    ],
                )
            ],
            unreferenced=[],
        )
        index = ["comp-a"]

        view = build_component_first(config, index)

        comp_a = view.components[0]
        param_edge = comp_a.parameters[0]
        assert param_edge.parameter_name == "testParam"
        assert param_edge.setting_name == "Test Parameter"
        assert param_edge.schema.name == "testSchema"
        assert param_edge.value == "test-value"
        assert param_edge.pointer == "config.test"


class TestUnreferencedParametersFunction:
    """Tests for the unreferenced_parameters helper function."""

    def test_unreferenced_parameters_none_when_all_referenced(self) -> None:
        """Should return empty list when all parameters are referenced."""
        referenced = {"param1", "param2"}
        all_params = {"param1", "param2"}

        orphans = unreferenced_parameters(all_params, referenced)

        assert orphans == []

    def test_unreferenced_parameters_finds_orphans(self) -> None:
        """Should return parameters not in the referenced set."""
        referenced = {"param1"}
        all_params = {"param1", "orphan1", "orphan2"}

        orphans = unreferenced_parameters(all_params, referenced)

        assert set(orphans) == {"orphan1", "orphan2"}
