"""Push service: orchestrate artifact pushing to OCI registries."""

from pathlib import Path

from margot import console
from margot.domain.metadata import ComponentConfig, MargoYaml, load_margo_yaml
from margot.domain.models import BuildTarget, PackageType
from margot.domain.tags import validate_oci_tag, validate_semver
from margot.infra import credentials, oci


def push(  # noqa: PLR0913
    package_type: PackageType,
    *,
    project_dir: str = ".",
    build_dir: str = ".dist",
    registry: str | None = None,
    repository: str | None = None,
    variant: str | None = None,
) -> list[BuildTarget]:
    """
    Push built artifacts from build_dir to OCI registry.

    Steps:
    1. Load margo.yaml from project_dir.
    2. Resolve registry/repository.
    3. Resolve push targets based on package_type.
    4. For each target: validate, check credentials, verify artifact, push.
    5. Return list of BuildTarget describing what was pushed.

    Args:
        package_type: PackageType.MARGO, COMPOSE, QUADLET, or ALL.
        project_dir: Directory containing margo.yaml (default ".").
        build_dir: Directory containing built artifacts (default ".dist").
        registry: OCI registry base URL (overrides margo.yaml).
        repository: Repository path (overrides margo.yaml).
        variant: For COMPOSE/QUADLET, push specific variant only (optional).

    Returns:
        List of BuildTarget objects representing pushed artifacts.

    Raises:
        ValueError: If margo.yaml not found, invalid, or push fails.
    """
    # Step 1: Load margo.yaml
    margo_yaml_path = str(Path(project_dir) / "margo.yaml")
    meta = load_margo_yaml(margo_yaml_path)
    console.info(f"Loaded margo.yaml: {margo_yaml_path}")

    # Step 2 & 3: Resolve and push targets
    targets: list[BuildTarget] = []

    if package_type == PackageType.ALL:
        targets = _push_all(meta, build_dir, registry, repository, variant)
    elif package_type == PackageType.MARGO:
        targets.append(_push_margo(meta, build_dir, registry, repository))
    elif package_type == PackageType.COMPOSE:
        targets.extend(_push_compose_or_quadlet(meta, build_dir, registry, repository, variant, PackageType.COMPOSE))
    elif package_type == PackageType.QUADLET:
        targets.extend(_push_compose_or_quadlet(meta, build_dir, registry, repository, variant, PackageType.QUADLET))
    else:
        raise ValueError(f"Unsupported package_type: {package_type}")  # pragma: no cover

    console.info(f"Push complete: {len(targets)} target(s).")
    return targets


def _push_all(
    meta: MargoYaml,
    build_dir: str,
    registry: str | None,
    repository: str | None,
    variant: str | None,
) -> list[BuildTarget]:
    """Push all components, skipping any not defined in margo.yaml."""
    targets: list[BuildTarget] = []

    targets.append(_push_margo(meta, build_dir, registry, repository))

    try:
        targets.extend(_push_compose_or_quadlet(meta, build_dir, registry, repository, variant, PackageType.COMPOSE))
    except ValueError as e:
        if "not defined in margo.yaml" in str(e):
            console.info("Skipping compose: not defined in margo.yaml")
        else:
            raise

    try:
        targets.extend(_push_compose_or_quadlet(meta, build_dir, registry, repository, variant, PackageType.QUADLET))
    except ValueError as e:
        if "not defined in margo.yaml" in str(e):
            console.info("Skipping quadlet: not defined in margo.yaml")
        else:
            raise

    return targets


def _resolve_registry_repository(
    component_repository: str | None,
    cli_registry: str | None,
    cli_repository: str | None,
) -> tuple[str, str]:
    """Resolve registry and repository from CLI args and component config.

    Priority:
    1. CLI args (registry + repository) — highest priority.
    2. Component-level repository field from margo.yaml — parsed as <registry>/<rest>.

    Args:
        component_repository: The component's repository field from margo.yaml.
        cli_registry: Registry from CLI --registry flag.
        cli_repository: Repository from CLI --repository flag.

    Returns:
        Tuple of (registry, repository).

    Raises:
        ValueError: If neither CLI args nor component config provide registry/repository.
    """
    if cli_registry and cli_repository:
        return cli_registry, cli_repository

    if cli_registry and not cli_repository:
        # Registry given but no repository — try component
        if component_repository:
            # Component repository might be just the path part
            _, repo = _parse_component_repository(component_repository)
            return cli_registry, repo
        raise ValueError("--repository is required when --registry is specified without a component repository in margo.yaml")

    if not cli_registry and cli_repository:
        # Repository given but no registry — try component
        if component_repository:
            reg, _ = _parse_component_repository(component_repository)
            return reg, cli_repository
        raise ValueError("--registry is required when --repository is specified without a component repository in margo.yaml")

    # Neither CLI arg given — fall back to component repository
    if component_repository:
        return _parse_component_repository(component_repository)

    raise ValueError("No registry/repository specified. Use --registry and --repository flags or set 'repository' in margo.yaml.")


def _parse_component_repository(repo_field: str) -> tuple[str, str]:
    """Parse a component repository field as <registry>/<rest>.

    Args:
        repo_field: Full repository string (e.g. 'public.ecr.aws/g2n4p2m7/margo').

    Returns:
        Tuple of (registry, repository_path).

    Raises:
        ValueError: If cannot be split into registry + path.
    """
    registry, _, rest = repo_field.partition("/")
    if not registry or not rest:
        raise ValueError(f"Cannot parse component repository '{repo_field}' as <registry>/<path>")
    return registry, rest


def _push_margo(
    meta: MargoYaml,
    build_dir: str,
    cli_registry: str | None,
    cli_repository: str | None,
) -> BuildTarget:
    """Push margo component."""
    version = meta.version

    # Validate version
    validate_oci_tag(version)
    validate_semver(version)

    # Resolve registry/repository
    resolved_registry, resolved_repository = _resolve_registry_repository(
        meta.repository, cli_registry, cli_repository
    )

    # Check credentials
    console.info(f"Checking credentials for {resolved_registry}")
    credentials.check_credentials(resolved_registry)

    # Verify artifact exists
    margo_dir = Path(build_dir) / version / "margo"
    app_yaml = margo_dir / "app.yaml"
    if not app_yaml.exists():
        raise ValueError(f"Built margo artifact not found: {app_yaml}")

    # Push
    console.info(f"Pushing margo: {resolved_registry}/{resolved_repository}:{version}")
    client = oci.OrasClient()
    client.push_margo(
        build_dir=build_dir,
        version=version,
        registry=resolved_registry,
        repository=resolved_repository,
        name=meta.name,
        description=meta.description,
    )

    return BuildTarget(
        package_type=PackageType.MARGO,
        variant_name=None,
        version=version,
        source_dir=str(margo_dir),
        output_dir=str(margo_dir),
        artifact_path=str(margo_dir),
    )


def _push_compose_or_quadlet(  # noqa: PLR0913
    meta: MargoYaml,
    build_dir: str,
    cli_registry: str | None,
    cli_repository: str | None,
    variant: str | None,
    component_type: PackageType,
) -> list[BuildTarget]:
    """Push compose or quadlet component(s)."""
    component_name = component_type.value
    component = meta.compose if component_type == PackageType.COMPOSE else meta.quadlet
    if component is None:
        raise ValueError(f"{component_name} component not defined in margo.yaml")

    if not component.variants:
        # Flat layout (no variants)
        return _push_flat_component(meta, component, build_dir, cli_registry, cli_repository, variant, component_type)

    # Variant layout
    return _push_variant_component(meta, component, build_dir, cli_registry, cli_repository, variant, component_type)


def _push_flat_component(  # noqa: PLR0913
    meta: MargoYaml,
    component: ComponentConfig,
    build_dir: str,
    cli_registry: str | None,
    cli_repository: str | None,
    variant: str | None,
    component_type: PackageType,
) -> list[BuildTarget]:
    """Push component with flat layout (no variants)."""
    component_name = component_type.value

    if variant is not None:
        raise ValueError(f"no variants declared in margo.yaml; --variant not supported for {component_name}")

    version = component.version
    if version is None:
        raise ValueError(f"{component_name} version not specified in margo.yaml")

    # Validate version
    validate_oci_tag(version)
    validate_semver(version)

    # Resolve registry/repository
    resolved_registry, resolved_repository = _resolve_registry_repository(
        component.repository, cli_registry, cli_repository
    )

    # Check credentials
    console.info(f"Checking credentials for {resolved_registry}")
    credentials.check_credentials(resolved_registry)

    # Verify artifact exists
    archive_path = Path(build_dir) / version / f"{meta.name}-{version}.tgz"
    if not archive_path.exists():
        raise ValueError(f"Built {component_name} artifact not found: {archive_path}")

    # Push
    console.info(f"Pushing {component_name}: {resolved_registry}/{resolved_repository}:{version}")
    client = oci.OrasClient()
    push_method = client.push_compose if component_type == PackageType.COMPOSE else client.push_quadlet
    push_method(
        archive_path=str(archive_path),
        version=version,
        registry=resolved_registry,
        repository=resolved_repository,
        name=meta.name,
        description=meta.description,
    )

    return [
        BuildTarget(
            package_type=component_type,
            variant_name=None,
            version=version,
            source_dir=str(archive_path),
            output_dir=str(archive_path.parent),
            artifact_path=str(archive_path),
        )
    ]


def _push_variant_component(  # noqa: PLR0913
    meta: MargoYaml,
    component: ComponentConfig,
    build_dir: str,
    cli_registry: str | None,
    cli_repository: str | None,
    variant: str | None,
    component_type: PackageType,
) -> list[BuildTarget]:
    """Push component with variant layout."""
    component_name = component_type.value
    targets: list[BuildTarget] = []

    # Determine which variants to push
    if variant is None:
        variants_to_push = list(component.variants)
    else:
        matching = [v for v in component.variants if v.name == variant]
        if not matching:
            raise ValueError(f"variant '{variant}' not declared in margo.yaml")
        variants_to_push = matching

    for v in variants_to_push:
        version = v.version
        if version is None:
            if component.version is None:
                raise ValueError(
                    f"{component_name} base version is required when variant '{v.name}' omits version"
                )
            version = f"{component.version}+{component_type.value}-{v.name}"
        version = version.replace("+", "_")

        # Validate version
        validate_oci_tag(version)
        validate_semver(version)

        # Resolve registry/repository
        resolved_registry, resolved_repository = _resolve_registry_repository(
            component.repository, cli_registry, cli_repository
        )

        # Check credentials
        console.info(f"Checking credentials for {resolved_registry}")
        credentials.check_credentials(resolved_registry)

        # Verify artifact exists
        archive_path = Path(build_dir) / version / f"{meta.name}-{version}.tgz"
        if not archive_path.exists():
            raise ValueError(f"Built {component_name} artifact not found: {archive_path}")

        # Push
        console.info(f"Pushing {component_name} variant '{v.name}': {resolved_registry}/{resolved_repository}:{version}")
        client = oci.OrasClient()
        push_method = client.push_compose if component_type == PackageType.COMPOSE else client.push_quadlet
        push_method(
            archive_path=str(archive_path),
            version=version,
            registry=resolved_registry,
            repository=resolved_repository,
            name=meta.name,
            description=meta.description,
        )

        targets.append(
            BuildTarget(
                package_type=component_type,
                variant_name=v.name,
                version=version,
                source_dir=str(archive_path),
                output_dir=str(archive_path.parent),
                artifact_path=str(archive_path),
            )
        )

    return targets
