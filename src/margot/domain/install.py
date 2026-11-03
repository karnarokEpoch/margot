"""Pure domain logic for `margot install` (quadlet profiles).

Covers profile selection, component validation, payload and merge checks, unit-to-service
derivation (sprint-13 spike S1), the ownership marker and the plan model. No I/O, no console,
no rich imports.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from margot.domain.layers import sanitize_filename
from margot.domain.uri import strip_scheme

MARKER_FILENAME = ".margot-install.json"
MARKER_SCHEMA = 1
MARKER_STATES = ("installing", "installed")

# Quadlet source suffixes accepted by the Podman generator on the reference host (S1).
QUADLET_SUFFIXES = (".container", ".volume", ".network", ".pod", ".image", ".build", ".kube", ".artifact")
# These suffixes generate a service named <stem>.service; the others <stem>-<suffix>.service.
_PLAIN_SERVICE_SUFFIXES = (".container", ".kube")
# Units that a user starts directly; the others are pulled in by their dependents (S1).
START_SUFFIXES = (".container", ".kube", ".pod")
COMPOSE_FILE_NAMES = frozenset({"compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"})

_NOT_INSTALLABLE_REASONS = {
    "compose": "compose profiles are not supported yet (compose apply is a later release)",
    "helm": "helm profiles are not supported (no cluster on the host)",
}


@dataclass(frozen=True)
class ComponentSpec:
    """A quadlet component of the selected profile, located by OCI repository and revision."""

    name: str
    repository: str
    revision: str

    @property
    def tag(self) -> str:
        """Archive tag as written by `margot build`: the revision with '+' replaced by '_'."""
        return self.revision.replace("+", "_")

    @property
    def reference(self) -> str:
        """OCI reference `<repository>:<revision>`."""
        return f"{self.repository}:{self.revision}"


@dataclass(frozen=True)
class ComponentFiles:
    """Relative file paths extracted from one component's archive, with the artifact they came from."""

    name: str
    source_key: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class UnitFile:
    """A quadlet unit file in the merged install tree and the service systemd derives from it."""

    relpath: str
    service: str


@dataclass(frozen=True)
class MergedLayout:
    """Result of merging all components into one install directory.

    Attributes:
        owners: Relative path -> name of the component that ships it.
        units: Quadlet unit files in first-seen order.
    """

    owners: dict[str, str]
    units: tuple[UnitFile, ...]


@dataclass(frozen=True)
class SourceRecord:
    """Where the install came from (marker `source`)."""

    kind: str
    uri: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Serialise without empty fields."""
        data = {"kind": self.kind}
        if self.uri is not None:
            data["uri"] = self.uri
        if self.path is not None:
            data["path"] = self.path
        return data


@dataclass(frozen=True)
class ComponentEntry:
    """One installed component (marker `components[]`)."""

    name: str
    repository: str | None
    revision: str
    archive_sha256: str
    files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialise with the marker's camelCase keys."""
        data: dict[str, Any] = {"name": self.name}
        if self.repository is not None:
            data["repository"] = self.repository
        data["revision"] = self.revision
        data["archiveSha256"] = self.archive_sha256
        data["files"] = list(self.files)
        return data


@dataclass(frozen=True)
class InstallRecord:
    """The ownership marker `<application-id>/.margot-install.json` (sprint-13 §3.8)."""

    state: str
    app_id: str
    app_name: str
    app_version: str
    profile_id: str
    installed_at: str
    source: SourceRecord
    components: tuple[ComponentEntry, ...]
    services: tuple[str, ...]
    parameters: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the marker's JSON shape (schema 1)."""
        return {
            "schema": MARKER_SCHEMA,
            "state": self.state,
            "appId": self.app_id,
            "appName": self.app_name,
            "appVersion": self.app_version,
            "profileId": self.profile_id,
            "installedAt": self.installed_at,
            "source": self.source.to_dict(),
            "components": [component.to_dict() for component in self.components],
            "services": list(self.services),
            "parameters": list(self.parameters),
        }


@dataclass(frozen=True)
class PlanComponent:
    """A component as shown in the plan: what it is installed from and what it generates."""

    entry: ComponentEntry
    reference: str
    services: tuple[str, ...]


@dataclass(frozen=True)
class InstallPlan:
    """Everything `install` will do, computed before the host is touched."""

    app_id: str
    app_name: str
    app_version: str
    profile_id: str
    source: SourceRecord
    target_dir: str
    components: tuple[PlanComponent, ...]
    units: tuple[UnitFile, ...]
    unapplied: tuple[str, ...]

    @property
    def services(self) -> tuple[str, ...]:
        """Every generated service, in unit order."""
        return tuple(unit.service for unit in self.units)

    @property
    def files(self) -> tuple[str, ...]:
        """Every payload file that will be written, in component order."""
        return tuple(path for component in self.components for path in component.entry.files)


def select_profile(doc: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
    """Select the deployment profile to install (sprint-13 §3.3).

    Args:
        doc: Parsed application description.
        profile_id: The `--profile` value, or None to select the single quadlet profile.

    Returns:
        The selected profile mapping.

    Raises:
        ValueError: No profiles, unknown id, non-installable id, no or several quadlet profiles.
    """
    profiles = [profile for profile in doc.get("deploymentProfiles") or [] if isinstance(profile, dict)]
    if not profiles:
        raise ValueError("The application description has no deployment profiles.")

    if profile_id is not None:
        match = next((profile for profile in profiles if profile.get("id") == profile_id), None)
        if match is None:
            raise ValueError(f"No deployment profile with id '{profile_id}'. Available: {_describe_profiles(profiles)}.")
        profile_type = match.get("type")
        if profile_type != "quadlet":
            reason = _NOT_INSTALLABLE_REASONS.get(str(profile_type), f"type '{profile_type}' is not installable")
            raise ValueError(f"Deployment profile '{profile_id}' cannot be installed: {reason}.")
        return match

    quadlets = [profile for profile in profiles if profile.get("type") == "quadlet"]
    if not quadlets:
        raise ValueError(f"No quadlet deployment profile to install. Available: {_describe_profiles(profiles)}.")
    if len(quadlets) > 1:
        ids = ", ".join(str(profile.get("id")) for profile in quadlets)
        raise ValueError(f"Several quadlet deployment profiles ({ids}). Choose one with --profile.")
    return quadlets[0]


def component_specs(profile: dict[str, Any]) -> list[ComponentSpec]:
    """Validate every component of a profile before anything is staged (sprint-13 §3.3).

    Raises:
        ValueError: No components, an unnamed or duplicated component, a component without
            repository and revision (including packageLocation), or an unsafe name.
    """
    profile_id = profile.get("id")
    components = profile.get("components") or []
    if not components:
        raise ValueError(f"Deployment profile '{profile_id}' has no components.")

    specs: list[ComponentSpec] = []
    seen: set[str] = set()
    for index, component in enumerate(components, start=1):
        if not isinstance(component, dict):
            raise TypeError(f"Component #{index} of profile '{profile_id}' is not a mapping.")
        name = component.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Component #{index} of profile '{profile_id}' has no name.")
        props = component.get("properties") if isinstance(component.get("properties"), dict) else {}
        repository = props.get("repository")
        revision = props.get("revision")
        if not _is_text(repository) or not _is_text(revision):
            if "packageLocation" in props:
                raise ValueError(
                    f"Component '{name}' is located by packageLocation, which install does not support yet. "
                    "Only OCI components (properties.repository and properties.revision) can be installed."
                )
            raise ValueError(
                f"Component '{name}' has no properties.repository and properties.revision; install needs an OCI component."
            )
        if sanitize_filename(name) is None:
            raise ValueError(f"Component name '{name}' cannot be used as a directory name.")
        if name in seen:
            raise ValueError(f"Component name '{name}' is declared more than once in profile '{profile_id}'.")
        seen.add(name)
        specs.append(ComponentSpec(name=name, repository=strip_scheme(repository.strip()), revision=revision.strip()))
    return specs


def application_dir_name(app_id: str) -> str:
    """Return the install directory name for an application id.

    Raises:
        ValueError: If the id cannot be used as a single directory name.
    """
    safe = sanitize_filename(app_id) if isinstance(app_id, str) else None
    if safe is None:
        raise ValueError(f"Application id '{app_id}' cannot be used as a directory name.")
    return safe


def is_quadlet_file(relpath: str) -> bool:
    """True when the file name carries a quadlet source suffix."""
    return PurePosixPath(relpath).name.endswith(QUADLET_SUFFIXES)


def unit_service_name(relpath: str) -> str:
    """Return the systemd service a quadlet unit file generates (spike S1).

    `<stem>.container` and `<stem>.kube` give `<stem>.service`; every other suffix gives
    `<stem>-<suffix>.service`. Only the file name matters, not the directory.

    Raises:
        ValueError: If the file is not a quadlet unit.
    """
    name = PurePosixPath(relpath).name
    stem, _, suffix = name.rpartition(".")
    if not is_quadlet_file(name) or not stem:
        raise ValueError(f"'{relpath}' is not a quadlet unit file.")
    if f".{suffix}" in _PLAIN_SERVICE_SUFFIXES:
        return f"{stem}.service"
    return f"{stem}-{suffix}.service"


def check_payload(component_name: str, relpaths: list[str]) -> None:
    """Require at least one quadlet unit at the root of a component payload (sprint-13 §3.4).

    Raises:
        ValueError: If the payload has no root-level quadlet unit. A compose payload gets a
            specific message, because a flat compose and quadlet build share one path.
    """
    roots = [path for path in relpaths if "/" not in path]
    if any(is_quadlet_file(path) for path in roots):
        return
    if any(path in COMPOSE_FILE_NAMES for path in roots):
        raise ValueError(
            f"Component '{component_name}' ships a compose file, not quadlet units. The artifact is probably "
            "the compose layer of a flat compose/quadlet build; install it with a compose profile or fix the artifact."
        )
    raise ValueError(
        f"Component '{component_name}' has no quadlet unit (.container, .volume, .network, .pod, .image, "
        ".build, .kube or .artifact) at the top of its payload."
    )


def merge_components(components: list[ComponentFiles]) -> MergedLayout:
    """Merge components into one install directory and derive the unit list (sprint-13 §3.4).

    Two components may ship the same path only when they come from the same artifact (one
    artifact installed under two component names). Two different unit files may not generate
    the same service, because Quadlet would load only one of them.

    Raises:
        ValueError: On a path clash between components, or a service-name clash.
    """
    owners: dict[str, str] = {}
    sources: dict[str, str] = {}
    for component in components:
        for relpath in component.files:
            if relpath in owners:
                if sources[relpath] == component.source_key:
                    continue
                raise ValueError(f"Components '{owners[relpath]}' and '{component.name}' both ship '{relpath}'.")
            owners[relpath] = component.name
            sources[relpath] = component.source_key

    units: list[UnitFile] = []
    by_service: dict[str, str] = {}
    for relpath in owners:
        if not is_quadlet_file(relpath):
            continue
        service = unit_service_name(relpath)
        if service in by_service:
            raise ValueError(
                f"Units '{by_service[service]}' and '{relpath}' both generate '{service}'. "
                "Rename one unit file; Quadlet would load only one of them."
            )
        by_service[service] = relpath
        units.append(UnitFile(relpath=relpath, service=service))
    return MergedLayout(owners=owners, units=tuple(units))


def start_targets(units: tuple[UnitFile, ...] | list[UnitFile]) -> list[str]:
    """Services that the printed next-step commands start (containers, kubes, pods)."""
    return [unit.service for unit in units if PurePosixPath(unit.relpath).name.endswith(START_SUFFIXES)]


def unapplied_parameters(doc: dict[str, Any]) -> list[str]:
    """Declared parameter names that margot does not apply (all of them in Step 1)."""
    parameters = doc.get("parameters")
    if not isinstance(parameters, dict):
        return []
    return sorted(str(name) for name in parameters)


def record_from_dict(data: object) -> InstallRecord:
    """Read a marker mapping back into an InstallRecord.

    Raises:
        ValueError: If the mapping is not a schema-1 marker.
    """
    if not isinstance(data, dict):
        raise TypeError("install marker is not a JSON object")
    if data.get("schema") != MARKER_SCHEMA:
        raise ValueError(f"install marker has unsupported schema {data.get('schema')!r} (expected {MARKER_SCHEMA})")
    state = data.get("state")
    if state not in MARKER_STATES:
        raise ValueError(f"install marker has an invalid state {state!r}")
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    components = tuple(
        ComponentEntry(
            name=_text(item, "name"),
            repository=item.get("repository"),
            revision=_text(item, "revision"),
            archive_sha256=_text(item, "archiveSha256"),
            files=tuple(item.get("files") or []),
        )
        for item in data.get("components") or []
    )
    return InstallRecord(
        state=state,
        app_id=_text(data, "appId"),
        app_name=_text(data, "appName"),
        app_version=_text(data, "appVersion"),
        profile_id=_text(data, "profileId"),
        installed_at=_text(data, "installedAt"),
        source=SourceRecord(kind=_text(source, "kind"), uri=source.get("uri"), path=source.get("path")),
        components=components,
        services=tuple(data.get("services") or []),
        parameters=tuple(data.get("parameters") or []),
    )


def _text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise TypeError(f"install marker field '{key}' is missing or not a string")
    return value


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _describe_profiles(profiles: list[dict[str, Any]]) -> str:
    return ", ".join(f"{profile.get('id')} ({profile.get('type')})" for profile in profiles)
