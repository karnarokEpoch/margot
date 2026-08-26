"""Pure domain model for margot describe — transforms loaded dict into display dataclasses.

This layer contains no I/O, no console imports, no rich objects — only data classes
and transformation functions. All formatting and rendering happens in commands/.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    """Identity block: id, apiVersion, kind, name, version, description."""

    id: str | None = None
    api_version: str | None = None
    kind: str | None = None
    name: str | None = None
    version: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Author:
    """Catalog author entry: name, email (optional)."""

    name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class Organization:
    """Catalog organization entry: name, site (optional)."""

    name: str | None = None
    site: str | None = None


@dataclass(frozen=True)
class CatalogApplication:
    """Catalog application block: tagline, site, icon, etc."""

    tagline: str | None = None
    site: str | None = None
    icon: str | None = None
    description_file: str | None = None
    license_file: str | None = None
    release_notes: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Catalog:
    """Catalog block: application, author[], organization[]."""

    application: CatalogApplication | None = None
    author: list[Author] = field(default_factory=list)
    organization: list[Organization] = field(default_factory=list)


@dataclass(frozen=True)
class Component:
    """Component entry: name + properties (keys as they appear in document)."""

    name: str | None = None
    properties: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DeploymentProfile:
    """Deployment profile entry: type, id, description, requiredResources, components[]."""

    type: str | None = None
    id: str | None = None
    description: str | None = None
    components: list[Component] = field(default_factory=list)


def build_identity(doc: dict) -> Identity:
    """Transform the loaded descriptor into an Identity dataclass.

    Args:
        doc: The parsed descriptor dict.

    Returns:
        An Identity with top-level id/apiVersion/kind and metadata fields.
    """
    meta = doc.get("metadata") or {}
    return Identity(
        id=doc.get("id"),
        api_version=doc.get("apiVersion"),
        kind=doc.get("kind"),
        name=meta.get("name"),
        version=meta.get("version"),
        description=meta.get("description"),
    )


def build_catalog(doc: dict) -> Catalog | None:
    """Transform metadata.catalog into a Catalog dataclass, or None if absent.

    Args:
        doc: The parsed descriptor dict.

    Returns:
        A Catalog, or None if metadata.catalog is absent or empty.
    """
    meta = doc.get("metadata") or {}
    catalog_data = meta.get("catalog")

    if not catalog_data:
        return None

    # Build application block
    app_data = catalog_data.get("application") or {}
    app = CatalogApplication(
        tagline=app_data.get("tagline"),
        site=app_data.get("site"),
        icon=app_data.get("icon"),
        description_file=app_data.get("descriptionFile"),
        license_file=app_data.get("licenseFile"),
        release_notes=app_data.get("releaseNotes"),
        tags=app_data.get("tags") or [],
    )

    # Build author list
    authors = []
    for author_data in catalog_data.get("author") or []:
        authors.append(
            Author(
                name=author_data.get("name"),
                email=author_data.get("email"),
            )
        )

    # Build organization list
    orgs = []
    for org_data in catalog_data.get("organization") or []:
        orgs.append(
            Organization(
                name=org_data.get("name"),
                site=org_data.get("site"),
            )
        )

    # Return None if catalog is empty (no app, no authors, no orgs)
    if not (app.tagline or app.site or app.icon or app.description_file or app.license_file or app.release_notes or app.tags or authors or orgs):
        return None

    return Catalog(application=app if (app.tagline or app.site or app.icon or app.description_file or app.license_file or app.release_notes or app.tags) else None, author=authors, organization=orgs)


def build_deployment_profiles(doc: dict) -> list[DeploymentProfile]:
    """Transform deploymentProfiles[] into DeploymentProfile dataclasses.

    Args:
        doc: The parsed descriptor dict.

    Returns:
        A list of DeploymentProfile.
    """
    profiles_data = doc.get("deploymentProfiles") or []
    profiles = []

    for profile_data in profiles_data:
        components = []
        for component_data in profile_data.get("components") or []:
            components.append(
                Component(
                    name=component_data.get("name"),
                    properties=component_data.get("properties") or {},
                )
            )

        profiles.append(
            DeploymentProfile(
                type=profile_data.get("type"),
                id=profile_data.get("id"),
                description=profile_data.get("description"),
                components=components,
            )
        )

    return profiles


def component_index(doc: dict) -> list[str]:
    """Build a deduplicated, first-seen-order list of component names across all profiles.

    Args:
        doc: The parsed descriptor dict.

    Returns:
        A list of distinct component names in the order they were first seen.
    """
    seen: dict[str, None] = {}
    for profile in doc.get("deploymentProfiles") or []:
        for component in profile.get("components") or []:
            if (name := component.get("name")) is not None:
                seen.setdefault(name, None)
    return list(seen)
