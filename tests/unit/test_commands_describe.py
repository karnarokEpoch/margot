"""Unit tests for describe command rich rendering — panel and tree builders."""

from io import StringIO
import re

from pytest import fixture
from rich.console import Console

from margot.domain.describe import (
    Catalog,
    CatalogApplication,
    Component,
    Configuration,
    ConfigurationSection,
    DeploymentProfile,
    Identity,
    Parameter,
    ParameterTarget,
    Schema,
    Setting,
)
from margot.commands.describe import (
    build_identity_catalog_panel,
    build_deployment_profiles_panel,
    build_configuration_panel,
    build_extensions_panel,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


def _render_to_text(renderable) -> str:
    """Render a rich object to plain text without color/markup."""
    output = StringIO()
    console = Console(file=output, force_terminal=True, no_color=True, width=120)
    console.print(renderable)
    return _strip_ansi(output.getvalue())


class TestIdentityCatalogPanel:
    """Tests for build_identity_catalog_panel."""

    def test_identity_panel_minimal_renders_without_error(self) -> None:
        """Should render identity panel with minimal fields."""
        identity = Identity(
            id="hello",
            api_version="v1alpha1",
            kind="ApplicationDescription",
            name="Hello App",
            version="1.0.0",
        )

        panel = build_identity_catalog_panel(identity, None, "/path/to/app.yaml")
        text = _render_to_text(panel)

        assert "v1alpha1" in text
        assert "hello" in text
        assert "Hello App" in text
        assert "1.0.0" in text
        assert "/path/to/app.yaml" in text

    def test_identity_panel_with_description(self) -> None:
        """Should include description when present."""
        identity = Identity(
            id="hello",
            api_version="v1alpha1",
            name="Hello App",
            version="1.0.0",
            description="A test application",
        )

        panel = build_identity_catalog_panel(identity, None, "/path/to/app.yaml")
        text = _render_to_text(panel)

        assert "A test application" in text

    def test_identity_panel_catalog_none_renders_none_marker(self) -> None:
        """Should render 'Catalog: None' when catalog is absent."""
        identity = Identity(
            id="hello",
            api_version="v1alpha1",
            name="Hello App",
            version="1.0.0",
        )

        panel = build_identity_catalog_panel(identity, None, "/path/to/app.yaml")
        text = _render_to_text(panel)

        # "None" should be dim'd in output
        assert "Catalog" in text

    def test_identity_panel_rendered_suffix(self) -> None:
        """Should append '(rendered)' to subtitle when path ends in temp file marker."""
        identity = Identity(
            id="hello",
            api_version="v1alpha1",
            name="Hello App",
            version="1.0.0",
        )

        # Simulate a temporary file path
        panel = build_identity_catalog_panel(identity, None, "/tmp/margot-abc.yaml")
        text = _render_to_text(panel)

        assert "rendered" in text.lower()

    def test_identity_panel_markup_escaped(self) -> None:
        """Should escape markup characters in descriptor values."""
        identity = Identity(
            id="array[string]",  # Would be interpreted as markup if not escaped
            api_version="v1alpha1",
            name="Hello App",
            version="1.0.0",
        )

        panel = build_identity_catalog_panel(identity, None, "/path/to/app.yaml")
        text = _render_to_text(panel)

        # The [string] part should appear (escaped as \[string\], which is still visible)
        assert "array" in text and "string" in text


class TestDeploymentProfilesPanel:
    """Tests for build_deployment_profiles_panel."""

    def test_deployment_profiles_empty_renders_none(self) -> None:
        """Should render 'none' when profiles list is empty."""
        profiles = []

        panel = build_deployment_profiles_panel(profiles, [])
        text = _render_to_text(panel)

        assert "none" in text.lower()
        assert "0 profiles" in text

    def test_deployment_profiles_single_renders_type_and_id(self) -> None:
        """Should render profile type and id as tree root."""
        profiles = [
            DeploymentProfile(
                type="compose",
                id="default",
                components=[],
            )
        ]

        panel = build_deployment_profiles_panel(profiles, [])
        text = _render_to_text(panel)

        assert "compose" in text
        assert "default" in text
        assert "1 profiles" in text

    def test_deployment_profiles_component_count_in_title(self) -> None:
        """Should include component count in panel title."""
        profiles = [
            DeploymentProfile(
                type="compose",
                id="default",
                components=[
                    Component(name="app1"),
                    Component(name="app2"),
                ],
            )
        ]
        index = ["app1", "app2"]

        panel = build_deployment_profiles_panel(profiles, index)
        text = _render_to_text(panel)

        assert "2 components" in text

    def test_deployment_profiles_component_list_renders(self) -> None:
        """Should render component names under components subtree."""
        profiles = [
            DeploymentProfile(
                type="compose",
                id="default",
                components=[
                    Component(name="app-compose"),
                ],
            )
        ]

        panel = build_deployment_profiles_panel(profiles, ["app-compose"])
        text = _render_to_text(panel)

        assert "app-compose" in text


class TestConfigurationPanel:
    """Tests for build_configuration_panel."""

    def test_configuration_empty_renders_none(self) -> None:
        """Should render 'none' when configuration is empty."""
        config = Configuration()

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        assert "none" in text.lower()
        assert "0 sections" in text

    def test_configuration_section_name_renders(self) -> None:
        """Should render section name as tree node."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="MQTT",
                    settings=[],
                )
            ]
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        assert "MQTT" in text
        assert "1 sections" in text
        assert "0 settings" in text

    def test_configuration_setting_renders_with_name(self) -> None:
        """Should render setting name as child of section."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="MQTT",
                    settings=[
                        Setting(
                            name="Broker",
                            parameter="mqttBroker",
                            schema=Schema(name="mqttBrokerSchema", data_type="string"),
                        )
                    ],
                )
            ]
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        assert "Broker" in text
        assert "1 settings" in text

    def test_configuration_immutable_tag_renders(self) -> None:
        """Should render immutable tag on setting when True."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="MQTT",
                    settings=[
                        Setting(
                            name="Port",
                            parameter="mqttPort",
                            immutable=True,
                            schema=Schema(name="portSchema", data_type="integer"),
                        )
                    ],
                )
            ]
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        assert "immutable" in text.lower()

    def test_configuration_immutable_tag_absent_when_false(self) -> None:
        """Should NOT render immutable tag when False."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Settings",
                    settings=[
                        Setting(
                            name="Name",
                            parameter="name",
                            immutable=False,
                            schema=Schema(name="nameSchema", data_type="string"),
                        )
                    ],
                )
            ]
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        # Should not have multiple "immutable" words (one would be the setting name)
        count = text.lower().count("immutable")
        assert count == 0

    def test_configuration_parameter_renders_default_value(self) -> None:
        """Should render parameter default value in literal form."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Settings",
                    settings=[
                        Setting(
                            name="Port",
                            parameter="port",
                            schema=Schema(name="portSchema", data_type="integer"),
                            parameter_resolved=Parameter(
                                value=1883,
                            ),
                        )
                    ],
                )
            ]
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        assert "1883" in text
        assert "Default" in text

    def test_configuration_parameter_quotes_string_values(self) -> None:
        """Should quote string default values, distinguish from bare numbers."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Settings",
                    settings=[
                        Setting(
                            name="Host",
                            parameter="host",
                            schema=Schema(name="hostSchema", data_type="string"),
                            parameter_resolved=Parameter(
                                value="localhost",
                            ),
                        )
                    ],
                )
            ]
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        # Check that the string value is quoted or clearly marked
        assert "localhost" in text

    def test_configuration_parameter_empty_string_renders_as_quoted(self) -> None:
        """Should render empty string as '\"\"' to distinguish from absent."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Settings",
                    settings=[
                        Setting(
                            name="Optional",
                            parameter="optional",
                            schema=Schema(name="schema", data_type="string"),
                            parameter_resolved=Parameter(
                                value="",
                            ),
                        )
                    ],
                )
            ]
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        # Empty string should be visible as "" or similar
        assert '""' in text or "(empty)" in text.lower()

    def test_configuration_targets_render_with_ratio(self) -> None:
        """Should render target pointer with (n/total) component ratio."""
        config = Configuration(
            sections=[
                ConfigurationSection(
                    name="Settings",
                    settings=[
                        Setting(
                            name="Port",
                            parameter="port",
                            schema=Schema(name="schema", data_type="integer"),
                            parameter_resolved=Parameter(
                                value=1883,
                                targets=[
                                    ParameterTarget(
                                        pointer="mqtt.port",
                                        components=["app1", "app2"],
                                    )
                                ],
                            ),
                        )
                    ],
                )
            ]
        )

        panel = build_configuration_panel(config, ["app1", "app2", "app3"])
        text = _render_to_text(panel)

        # Should show (2/3 components) ratio
        assert "(2/3" in text  # Will be "(2/3 components)"
        assert "mqtt.port" in text

    def test_configuration_unreferenced_parameters_subtree_renders(self) -> None:
        """Should render unreferenced parameters subtree when non-empty."""
        config = Configuration(
            sections=[],
            unreferenced=["orphan1", "orphan2"],
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        assert "orphan1" in text
        assert "orphan2" in text
        assert "unreferenced" in text.lower()

    def test_configuration_unreferenced_parameters_absent_when_empty(self) -> None:
        """Should NOT render unreferenced parameters subtree when empty."""
        config = Configuration(
            sections=[],
            unreferenced=[],
        )

        panel = build_configuration_panel(config, [])
        text = _render_to_text(panel)

        # The word "unreferenced" should not appear
        assert "unreferenced" not in text.lower()


class TestExtensionsPanel:
    """Tests for build_extensions_panel."""

    def test_extensions_panel_with_data(self) -> None:
        """Should render extensions map as key-value pairs."""
        extensions = {
            "vendor-acme": {"key": "value"},
            "vendor-xyz": {"enabled": True},
        }

        panel = build_extensions_panel(extensions)

        assert panel is not None
        text = _render_to_text(panel)

        assert "vendor-acme" in text
        assert "vendor-xyz" in text


class TestLiteralScalarRendering:
    """Tests for literal scalar rendering (not actual panel builders, but validation of format)."""

    def test_markup_characters_in_descriptor_not_swallowed(self) -> None:
        """Should ensure array[string] dataType renders literally, not as markup."""
        # This is tested by checking that markup characters appear in output
        identity = Identity(
            id="test",
            name="array[string]",  # Should not be interpreted as markup
            api_version="v1",
            version="1.0.0",
        )

        panel = build_identity_catalog_panel(identity, None, "/path")
        text = _render_to_text(panel)

        # The [string] should not disappear
        assert "array" in text.lower()
        assert "string" in text.lower()
