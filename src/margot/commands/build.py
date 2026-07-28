"""Build command: compile Margo application components locally."""

from typing import Annotated

from typer import Option

from margot import console
from margot.domain.models import BuildTarget, PackageType
from margot.services import build as build_service


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


def _invoke_build(
    t: str,
    expanded_from_all: bool,
    build_dir: str,
    version: str | None,
    variant: str | None,
) -> list[BuildTarget]:
    """Call build service for one type. Returns targets or [] if component is missing and expanded_from_all."""
    package_type = PackageType(t)
    try:
        return build_service.build(
            package_type,
            project_dir=".",
            build_dir=build_dir,
            version_override=version,
            variant=variant,
        )
    except ValueError as e:
        if expanded_from_all and "not defined in margo.yaml" in str(e):
            console.info(f"Skipping {t}: not defined in margo.yaml")
            return []
        raise


def build_cmd(
    types: Annotated[
        list[str] | None,
        Option("--type", "-t", help="Package type(s) to build (margo|compose|quadlet|all). Repeatable."),
    ] = None,
    version: str | None = Option(None, "--version", "-v", help="Override version for all components."),
    build_dir: str = Option(".dist", "--build-dir", help="Output directory for built artifacts."),
    variant: str | None = Option(None, "--variant", help="Build a specific variant (compose/quadlet only)."),
) -> None:
    """Build Margo application package types locally."""
    resolved, expanded_from_all = _resolve_types(types)

    all_targets: list[BuildTarget] = []
    try:
        for t in resolved:
            all_targets.extend(_invoke_build(t, expanded_from_all, build_dir, version, variant))

        if all_targets:
            for target in all_targets:
                if target.variant_name:
                    console.success(f"Built ({target.variant_name}): {target.output_dir}")
                else:
                    console.success(f"Built: {target.output_dir}")
        else:
            console.warning("Nothing was built.")

    except ValueError as e:
        console.fatal(str(e))
    except Exception as e:  # noqa: BLE001
        console.fatal(f"Build failed: {e}")
