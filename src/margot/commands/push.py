"""Push command: push built Margo artifacts to OCI registries."""

from typing import Annotated

from typer import Option

from margot import console
from margot.domain.models import BuildTarget, PackageType
from margot.services import push as push_service


def _resolve_types(types: list[str] | None) -> tuple[list[str], bool]:
    """Validate and expand --type values. Returns (resolved_types, expanded_from_all)."""
    if not types:
        return ["margo", "compose", "quadlet"], True

    valid_types = ("margo", "compose", "quadlet", "all")
    for t in types:
        if t not in valid_types:
            console.fatal(f"invalid --type '{t}'. Must be one of: margo, compose, quadlet, all")

    if "all" in types:
        return ["margo", "compose", "quadlet"], True

    # Deduplicate preserving order
    seen: set[str] = set()
    resolved: list[str] = []
    for t in types:
        if t not in seen:
            resolved.append(t)
            seen.add(t)
    return resolved, False


def _invoke_push(  # noqa: PLR0913
    t: str,
    expanded_from_all: bool,
    build_dir: str,
    registry: str | None,
    repository: str | None,
    variant: str | None,
) -> list[BuildTarget]:
    """Call push service for one type. Returns targets or [] if component is missing and expanded_from_all."""
    package_type = PackageType(t)
    try:
        return push_service.push(
            package_type,
            project_dir=".",
            build_dir=build_dir,
            registry=registry,
            repository=repository,
            variant=variant,
        )
    except ValueError as e:
        if expanded_from_all and "not defined in margo.yaml" in str(e):
            console.info(f"Skipping {t}: not defined in margo.yaml")
            return []
        raise


def push_cmd(
    types: Annotated[
        list[str] | None,
        Option("--type", "-t", help="Package type(s) to push (margo|compose|quadlet|all). Repeatable."),
    ] = None,
    registry: str | None = Option(None, "--registry", help="OCI registry base URL."),
    repository: str | None = Option(None, "--repository", help="Repository path."),
    build_dir: str = Option(".dist", "--build-dir", help="Directory containing built artifacts."),
    variant: str | None = Option(None, "--variant", help="Push a specific variant (compose/quadlet only)."),
) -> None:
    """Push built Margo application artifacts to an OCI registry."""
    resolved, expanded_from_all = _resolve_types(types)

    all_targets: list[BuildTarget] = []
    try:
        for t in resolved:
            all_targets.extend(_invoke_push(t, expanded_from_all, build_dir, registry, repository, variant))

        if all_targets:
            for target in all_targets:
                if target.registry and target.repository:
                    full_ref = f"{target.registry}/{target.repository}:{target.version}"
                else:
                    full_ref = target.version
                if target.variant_name:
                    console.success(f"Pushed ({target.variant_name}): {full_ref}")
                else:
                    console.success(f"Pushed: {full_ref}")
        else:
            console.warning("Nothing was pushed.")

    except ValueError as e:
        console.fatal(str(e))
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Push failed: {e}")
