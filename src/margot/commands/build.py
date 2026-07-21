"""Build command: compile Margo application components locally."""

from typing import Annotated, Optional

from typer import Option

from margot import console
from margot.domain.models import PackageType
from margot.services import build as build_service


def build_cmd(
    types: Annotated[
        Optional[list[str]],
        Option("--type", "-t", help="Package type(s) to build (margo|compose|quadlet|all). Repeatable."),
    ] = None,
    version: str | None = Option(None, "--version", "-v", help="Override version for all components."),
    build_dir: str = Option(".dist", "--build-dir", help="Output directory for built artifacts."),
    variant: str | None = Option(None, "--variant", help="Build a specific variant (compose/quadlet only)."),
) -> None:
    """Build Margo application package types locally."""
    # Default to ["all"] when no -t flags supplied
    if not types:
        types = ["all"]

    # Validate each type value
    valid_types = ("margo", "compose", "quadlet", "all")
    for t in types:
        if t not in valid_types:
            console.fatal(f"invalid --type '{t}'. Must be one of: margo, compose, quadlet, all")

    # Expand "all" → all three types; otherwise deduplicate preserving order.
    # Track whether the expansion came from "all" so we can skip missing components.
    expanded_from_all = "all" in types
    if expanded_from_all:
        resolved: list[str] = ["margo", "compose", "quadlet"]
    else:
        seen: set[str] = set()
        resolved = []
        for t in types:
            if t not in seen:
                resolved.append(t)
                seen.add(t)

    all_targets = []
    try:
        for t in resolved:
            package_type = PackageType(t)
            try:
                targets = build_service.build(
                    package_type,
                    project_dir=".",
                    build_dir=build_dir,
                    version_override=version,
                    variant=variant,
                )
            except ValueError as e:
                # When expanding "all", skip components that aren't defined.
                # Any other ValueError (bad version, invalid tag, etc.) must propagate.
                if expanded_from_all and "not defined in margo.yaml" in str(e):
                    console.info(f"Skipping {t}: not defined in margo.yaml")
                    continue
                raise
            all_targets.extend(targets)

        # Output results
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
