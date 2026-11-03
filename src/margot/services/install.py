"""Service layer for `margot install` (quadlet profiles).

``prepare_install`` resolves the source, selects the profile, stages every component archive and
builds the plan. It never touches systemd or the Quadlet directory. ``apply_install`` is the only
function that writes to the host: it checks the systemd user session and ownership, places the
files, maintains the marker and reloads systemd. It never starts, enables or stops a unit.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from margot import console
from margot.domain import install as domain
from margot.domain.install import (
    ComponentEntry,
    ComponentFiles,
    ComponentSpec,
    InstallPlan,
    InstallRecord,
    PlanComponent,
    SourceRecord,
)
from margot.domain.install_parameters import dropin_relpath, render_dropin, resolve_parameters, variables_by_unit
from margot.domain.layers import sanitize_filename
from margot.domain.metadata import load_margo_yaml
from margot.domain.models import PackageType
from margot.infra import install_store, systemd
from margot.infra.filesystem import extract_tar_archive, sha256_file
from margot.infra.install_store import quadlet_root
from margot.services import describe as describe_service
from margot.services import pull as pull_service
from margot.services import remote as remote_service
from margot.services import verify as verify_service

DEFAULT_BUILD_DIR = ".dist"
_STAGING_PREFIX = "margot-install-"


@dataclass(frozen=True)
class _Staged:
    """One archive extracted into staging."""

    sha256: str
    extracted: Path
    files: tuple[str, ...]


@dataclass(frozen=True)
class _ArchiveRef:
    """Where one component's archive is, before it is extracted."""

    spec: ComponentSpec
    key: str
    archive: Path
    reference: str


@dataclass
class PreparedInstall:
    """Everything prepared for an install. The caller must call ``cleanup`` in a ``finally``."""

    plan: InstallPlan
    files: dict[str, Path]
    temp_dir: TemporaryDirectory

    def cleanup(self) -> None:
        """Remove the staging directory."""
        self.temp_dir.cleanup()


@dataclass(frozen=True)
class InstallResult:
    """What apply_install did."""

    app_dir: Path
    services: tuple[str, ...]
    start_services: tuple[str, ...]
    wanted_services: tuple[str, ...]
    files: tuple[str, ...]


def detect_source(uri: str | None, project_dir: str | None) -> str:
    """Return ``remote``, ``project`` or ``static`` (sprint-13 §3.2)."""
    if uri is not None:
        return "remote"
    if (Path(project_dir or ".") / "margo.yaml").is_file():
        return "project"
    return "static"


def prepare_install(
    *,
    uri: str | None,
    project_dir: str | None,
    build_dir: str | None,
    profile_id: str | None,
    overrides: Mapping[str, str] | None = None,
) -> PreparedInstall:
    """Resolve, select, stage and plan an install. Nothing on the host is changed.

    Args:
        overrides: ``--set`` values by parameter name.

    Raises:
        ValueError: Any source, profile, component, payload, merge or parameter problem (exit 3).
        CredentialsExpiredError, OciRegistryError, OSError: Registry problems (exit 4 in the command).
    """
    kind = detect_source(uri, project_dir)
    temp_dir = TemporaryDirectory(prefix=_STAGING_PREFIX)
    try:
        staging = Path(temp_dir.name)
        if kind == "project":
            source, doc, refs = _from_project(project_dir or ".", build_dir or DEFAULT_BUILD_DIR, profile_id)
        elif kind == "remote":
            source, doc, refs = _from_remote(uri or "", profile_id, staging)
        else:
            source, doc, refs = _from_static(project_dir or ".", profile_id)
        profile = domain.select_profile(doc, profile_id)
        return _assemble(temp_dir, source, doc, profile, refs, overrides or {})
    except BaseException:
        temp_dir.cleanup()
        raise


def apply_install(prepared: PreparedInstall, *, root: Path) -> InstallResult:
    """Place the files under ``root/<application-id>/``, maintain the marker and reload systemd.

    Raises:
        systemd.SystemdError: Unusable user session, or daemon-reload failed (exit 1).
        ValueError: The application directory belongs to someone else or to another profile (exit 3).
    """
    plan = prepared.plan
    systemd.ensure_user_session()
    app_dir = root / domain.application_dir_name(plan.app_id)
    if str(app_dir) != plan.target_dir:
        raise ValueError(
            f"This install was prepared for {plan.target_dir}, not {app_dir}. QUADLET_DIR in the drop-ins names the "
            "prepared directory, so run install again."
        )
    existing = _check_ownership(app_dir, plan)
    installed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    install_store.write_marker(app_dir, _record(plan, "installing", installed_at))
    console.info(f"Writing {len(plan.files)} file(s) to {app_dir}")
    for relpath in plan.files:
        install_store.place_file(app_dir, relpath, prepared.files[relpath])

    previous = {path for component in existing.components for path in component.files} if existing else set()
    for stale in sorted(previous - set(plan.files)):
        install_store.remove_file(app_dir, stale)
    install_store.prune_empty_dirs(app_dir)
    install_store.write_marker(app_dir, _record(plan, "installed", installed_at))

    try:
        systemd.daemon_reload()
    except systemd.SystemdError as error:
        raise systemd.SystemdError(
            f"{error} Files were written to {app_dir} and nothing was rolled back. Fix the cause and run install again."
        ) from error

    return InstallResult(
        app_dir=app_dir,
        services=plan.services,
        start_services=tuple(domain.start_targets(plan.units)),
        wanted_services=tuple(unit.service for unit in plan.units if unit.default_target),
        files=plan.files,
    )


def _check_ownership(app_dir: Path, plan: InstallPlan) -> InstallRecord | None:
    """Return the marker of an existing margot installation of the same profile, or None for a fresh directory."""
    if not app_dir.exists():
        return None
    existing = install_store.read_marker(app_dir)
    if existing is None:
        raise ValueError(
            f"{app_dir} already exists but was not installed by margot. margot never adopts or overwrites "
            "a directory it did not create; move it away first."
        )
    if existing.profile_id != plan.profile_id or existing.app_id != plan.app_id:
        raise ValueError(
            f"{app_dir} holds an installation of profile '{existing.profile_id}' "
            f"(application '{existing.app_id}'), not '{plan.profile_id}'. Uninstall is not available yet; "
            "remove the directory by hand to switch profiles."
        )
    return existing


def _record(plan: InstallPlan, state: str, installed_at: str) -> InstallRecord:
    return InstallRecord(
        state=state,
        app_id=plan.app_id,
        app_name=plan.app_name,
        app_version=plan.app_version,
        profile_id=plan.profile_id,
        installed_at=installed_at,
        source=plan.source,
        components=tuple(component.entry for component in plan.components),
        services=plan.services,
        parameters=plan.parameters,
    )


def _from_project(
    project_dir: str, build_dir: str, profile_id: str | None
) -> tuple[SourceRecord, dict[str, Any], list[_ArchiveRef]]:
    """Built output only: the descriptor and archives come from the build directory, never the registry."""
    meta = load_margo_yaml(str(Path(project_dir) / "margo.yaml"))
    descriptor = Path(build_dir) / meta.version.replace("+", "_") / "margo" / "app.yaml"
    if not descriptor.is_file():
        raise ValueError(f"No built application description at {descriptor}. Run 'margot build -t all' first.")
    doc = describe_service.load_descriptor_from_path(str(descriptor)).descriptor
    specs = domain.component_specs(domain.select_profile(doc, profile_id))

    refs: list[_ArchiveRef] = []
    missing: list[str] = []
    for spec in specs:
        archive = Path(build_dir) / spec.tag / f"{meta.name}-{spec.tag}.tgz"
        if not archive.is_file():
            missing.append(f"{spec.name} ({archive})")
            continue
        refs.append(_ArchiveRef(spec=spec, key=str(archive), archive=archive, reference=str(archive)))
    if missing:
        raise ValueError(
            "Component(s) not built, or not built by this project: "
            + "; ".join(missing)
            + ". Run 'margot build -t all', or use 'margot install <uri>' for external components."
        )
    return SourceRecord(kind="project", path=str(descriptor)), doc, refs


def _from_static(folder: str, profile_id: str | None) -> tuple[SourceRecord, dict[str, Any], list[_ArchiveRef]]:
    """A `pull --recursive` folder: each component is <folder>/<name>/<one archive>."""
    resolved = verify_service.resolve_descriptor(folder)
    doc = describe_service.load_descriptor_from_path(resolved.path).descriptor
    base = Path(resolved.path).parent
    specs = domain.component_specs(domain.select_profile(doc, profile_id))

    refs: list[_ArchiveRef] = []
    for spec in specs:
        component_dir = base / str(sanitize_filename(spec.name))
        if not component_dir.is_dir():
            raise ValueError(
                f"Component '{spec.name}' is missing: expected folder {component_dir}. "
                "Run 'margot pull <uri> --recursive' to create it."
            )
        files = sorted(path for path in component_dir.iterdir() if path.is_file())
        if len(files) != 1:
            raise ValueError(f"Component folder {component_dir} must hold exactly one archive; found {len(files)} file(s).")
        refs.append(_ArchiveRef(spec=spec, key=str(component_dir), archive=files[0], reference=str(files[0])))
    return SourceRecord(kind="static", path=str(base)), doc, refs


def _from_remote(uri: str, profile_id: str | None, staging: Path) -> tuple[SourceRecord, dict[str, Any], list[_ArchiveRef]]:
    """A remote margo artifact: its descriptor, then each quadlet component pulled by reference."""
    resolved = remote_service.resolve_remote_descriptor(uri)
    try:
        normalized = resolved.normalized_uri
        doc = describe_service.load_descriptor_from_path(resolved.app_yaml_path, normalized).descriptor
    finally:
        resolved.temp_dir.cleanup()
    specs = domain.component_specs(domain.select_profile(doc, profile_id))

    refs: list[_ArchiveRef] = []
    pulled: dict[str, Path] = {}
    for index, spec in enumerate(specs):
        if spec.reference not in pulled:
            pulled[spec.reference] = _pull_component(spec, staging / f"pull-{index}")
        refs.append(_ArchiveRef(spec=spec, key=spec.reference, archive=pulled[spec.reference], reference=spec.reference))
    return SourceRecord(kind="remote", uri=normalized), doc, refs


def _pull_component(spec: ComponentSpec, outdir: Path) -> Path:
    """Pull one component artifact into ``outdir`` and return its single archive file."""
    prepared = pull_service.prepare_oci_retrieval(spec.reference)
    if prepared.package_type != PackageType.QUADLET:
        artifact = prepared.manifest.get("artifactType") or "unknown"
        raise ValueError(f"Component '{spec.name}' ({spec.reference}) is not a quadlet component (artifact type: {artifact}).")
    outdir.mkdir(parents=True)
    pull_service.pull_prepared_context(prepared, str(outdir))
    files = sorted(path for path in outdir.iterdir() if path.is_file())
    if len(files) != 1:
        raise ValueError(f"Component '{spec.name}' ({spec.reference}) must hold exactly one archive; found {len(files)} file(s).")
    return files[0]


def _stage(archive: Path, destination: Path) -> _Staged:
    """Extract one archive into staging and collect its relative file list and checksum."""
    extracted = destination / "tree"
    extract_tar_archive(archive, extracted)
    files = tuple(sorted(path.relative_to(extracted).as_posix() for path in extracted.rglob("*") if path.is_file()))
    return _Staged(sha256=sha256_file(str(archive)), extracted=extracted, files=files)


def _assemble(  # noqa: PLR0913 - one parameter per input of the plan
    temp_dir: TemporaryDirectory,
    source: SourceRecord,
    doc: dict[str, Any],
    profile: dict[str, Any],
    refs: list[_ArchiveRef],
    overrides: Mapping[str, str],
) -> PreparedInstall:
    """Stage every unique archive, validate payloads and merge, resolve parameters, then build the plan."""
    staging = Path(temp_dir.name)
    staged: dict[str, _Staged] = {}
    for ref in refs:
        if ref.key not in staged:
            staged[ref.key] = _stage(ref.archive, staging / f"component-{len(staged)}")

    components_files: list[ComponentFiles] = []
    for ref in refs:
        domain.check_payload(ref.spec.name, list(staged[ref.key].files))
        components_files.append(ComponentFiles(name=ref.spec.name, source_key=ref.key, files=staged[ref.key].files))
    layout = domain.merge_components(components_files)

    key_by_name = {ref.spec.name: ref.key for ref in refs}
    file_sources = {relpath: staged[key_by_name[owner]].extracted / relpath for relpath, owner in layout.owners.items()}
    units = tuple(
        replace(unit, default_target=domain.declares_default_target(_read_text(file_sources[unit.relpath])))
        for unit in layout.units
    )

    resolution = resolve_parameters(doc, [ref.spec.name for ref in refs], overrides)
    app_id = str(doc.get("id") or "")
    application_dir = quadlet_root() / domain.application_dir_name(app_id)
    units_by_component = {
        ref.spec.name: tuple(unit.relpath for unit in units if unit.relpath in staged[ref.key].files) for ref in refs
    }
    dropin_by_component: dict[str, list[str]] = {name: [] for name in units_by_component}
    for unit, variables in sorted(variables_by_unit(resolution.bindings, units_by_component, str(application_dir)).items()):
        relpath = dropin_relpath(unit)
        dropin = staging / "dropins" / relpath
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(render_dropin(variables), encoding="utf-8")
        dropin.chmod(0o600)
        file_sources[relpath] = dropin
        for name, unit_paths in units_by_component.items():
            if unit in unit_paths:
                dropin_by_component[name].append(relpath)

    plan_components: list[PlanComponent] = []
    for ref in refs:
        stage = staged[ref.key]
        entry = ComponentEntry(
            name=ref.spec.name,
            repository=ref.spec.repository,
            revision=ref.spec.revision,
            archive_sha256=stage.sha256,
            files=tuple(sorted({*stage.files, *dropin_by_component[ref.spec.name]})),
        )
        services = tuple(unit.service for unit in units if unit.relpath in stage.files)
        plan_components.append(PlanComponent(entry=entry, reference=ref.reference, services=services))

    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}

    plan = InstallPlan(
        app_id=app_id,
        app_name=str(metadata.get("name") or app_id),
        app_version=str(metadata.get("version") or ""),
        profile_id=str(profile.get("id")),
        source=source,
        target_dir=str(application_dir),
        components=tuple(plan_components),
        units=units,
        unapplied=resolution.unapplied,
        bindings=resolution.bindings,
    )
    return PreparedInstall(plan=plan, files=file_sources, temp_dir=temp_dir)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")
