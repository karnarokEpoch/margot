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


@dataclass(frozen=True)
class Schema:
    """Schema (constraint rules): dataType + validation rules."""

    name: str | None = None
    data_type: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    regex_match: str | None = None
    min_value: int | float | None = None
    max_value: int | float | None = None
    min_precision: int | None = None
    max_precision: int | None = None
    allow_empty: bool | None = None
    multiselect: bool | None = None
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParameterTarget:
    """Parameter target: pointer + components[] list."""

    pointer: str | None = None
    components: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Parameter:
    """Parameter: value/default + targets[]."""

    value: object = None
    targets: list[ParameterTarget] = field(default_factory=list)


@dataclass(frozen=True)
class Setting:
    """Configuration setting: parameter name, description, immutable, schema reference."""

    parameter: str | None = None
    name: str | None = None
    description: str | None = None
    immutable: bool = False
    schema: Schema | None = None
    parameter_resolved: Parameter | None = None


@dataclass(frozen=True)
class ConfigurationSection:
    """Configuration section: name + settings[]."""

    name: str | None = None
    settings: list[Setting] = field(default_factory=list)


@dataclass(frozen=True)
class Configuration:
    """Configuration block: sections[] + unreferenced parameters list."""

    sections: list[ConfigurationSection] = field(default_factory=list)
    unreferenced: list[str] = field(default_factory=list)


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
    authors = [
        Author(
            name=author_data.get("name"),
            email=author_data.get("email"),
        )
        for author_data in catalog_data.get("author") or []
    ]

    # Build organization list
    orgs = [
        Organization(
            name=org_data.get("name"),
            site=org_data.get("site"),
        )
        for org_data in catalog_data.get("organization") or []
    ]

    # Return None if catalog is empty (no app, no authors, no orgs)
    if not (
        app.tagline
        or app.site
        or app.icon
        or app.description_file
        or app.license_file
        or app.release_notes
        or app.tags
        or authors
        or orgs
    ):
        return None

    return Catalog(
        application=(
            app
            if (
                app.tagline
                or app.site
                or app.icon
                or app.description_file
                or app.license_file
                or app.release_notes
                or app.tags
            )
            else None
        ),
        author=authors,
        organization=orgs,
    )


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
        components = [
            Component(
                name=component_data.get("name"),
                properties=component_data.get("properties") or {},
            )
            for component_data in profile_data.get("components") or []
        ]

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


def build_configuration(doc: dict) -> Configuration:
    """Transform configuration into a Configuration dataclass with the configuration-first join.

    This is the heart of the describe command: walks sections -> settings -> (schema, parameter)
    -> targets -> components, building the entire tree in one traversal.

    Args:
        doc: The parsed descriptor dict.

    Returns:
        A Configuration with sections and unreferenced parameters.
    """
    config_data = doc.get("configuration") or {}
    parameters_map = doc.get("parameters") or {}

    # Build schema lookup: name -> Schema dataclass
    schemas_dict: dict[str, Schema] = {}
    for schema_data in config_data.get("schema") or []:
        schema_name = schema_data.get("name")
        if schema_name:
            schemas_dict[schema_name] = Schema(
                name=schema_name,
                data_type=schema_data.get("dataType"),
                min_length=schema_data.get("minLength"),
                max_length=schema_data.get("maxLength"),
                regex_match=schema_data.get("regexMatch"),
                min_value=schema_data.get("minValue"),
                max_value=schema_data.get("maxValue"),
                min_precision=schema_data.get("minPrecision"),
                max_precision=schema_data.get("maxPrecision"),
                allow_empty=schema_data.get("allowEmpty"),
                multiselect=schema_data.get("multiselect"),
                options=schema_data.get("options") or [],
            )

    # Track which parameters are referenced by settings
    referenced: set[str] = set()

    # Build sections with settings and the configuration-first join
    sections = []
    for section_data in config_data.get("sections") or []:
        settings = []
        for setting_data in section_data.get("settings") or []:
            param_name = setting_data.get("parameter")
            schema_name = setting_data.get("schema")

            # Track referenced parameters
            if param_name:
                referenced.add(param_name)

            # Look up schema by name
            schema_resolved = schemas_dict.get(schema_name) if schema_name else None

            # Look up parameter by name and build Parameter with targets
            parameter_resolved = None
            if param_name and param_name in parameters_map:
                param_data = parameters_map[param_name]
                targets = [
                    ParameterTarget(
                        pointer=target_data.get("pointer"),
                        components=target_data.get("components") or [],
                    )
                    for target_data in param_data.get("targets") or []
                ]
                parameter_resolved = Parameter(
                    value=param_data.get("value"),
                    targets=targets,
                )

            settings.append(
                Setting(
                    parameter=param_name,
                    name=setting_data.get("name"),
                    description=setting_data.get("description"),
                    immutable=setting_data.get("immutable", False),
                    schema=schema_resolved,
                    parameter_resolved=parameter_resolved,
                )
            )

        sections.append(
            ConfigurationSection(
                name=section_data.get("name"),
                settings=settings,
            )
        )

    # Compute unreferenced parameters
    orphans = unreferenced_parameters(set(parameters_map.keys()), referenced)

    return Configuration(
        sections=sections,
        unreferenced=orphans,
    )


def unreferenced_parameters(all_params: set[str], referenced: set[str]) -> list[str]:
    """Return the list of parameters not referenced by any setting.

    Args:
        all_params: All parameter names from the top-level parameters map.
        referenced: Parameter names referenced by at least one setting.

    Returns:
        A list of unreferenced parameter names, in iteration order.
    """
    return [name for name in all_params if name not in referenced]
