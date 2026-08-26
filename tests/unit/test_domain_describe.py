"""Unit tests for the describe domain model — identity, catalog, and deployment profiles."""

from pytest import raises

from margot.domain.describe import (
    Catalog,
    CatalogApplication,
    Component,
    DeploymentProfile,
    Identity,
    build_catalog,
    build_deployment_profiles,
    build_identity,
    component_index,
)


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
