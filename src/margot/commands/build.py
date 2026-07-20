"""Build command: compile Margo application components locally."""

from typer import Option

from margot import console
from margot.domain.models import PackageType
from margot.services import build as build_service


def build_cmd(
    type_: str = Option("all", "--type", "-t", help="Package type to build (margo|compose|quadlet|all)."),
    version: str | None = Option(None, "--version", "-v", help="Override version for all components."),
    build_dir: str = Option(".dist", "--build-dir", help="Output directory for built artifacts."),
    variant: str | None = Option(None, "--variant", help="Build a specific variant (compose/quadlet only)."),
) -> None:
    """Build Margo application package types locally."""
    # Validate --type is a known value
    valid_types = ("margo", "compose", "quadlet", "all")
    if type_ not in valid_types:
        console.fatal(f"invalid --type '{type_}'. Must be one of: margo, compose, quadlet, all")

    # Resolve package type (PackageType is StrEnum, so we can construct it directly)
    package_type = PackageType(type_)

    try:
        targets = build_service.build(
            package_type,
            project_dir=".",
            build_dir=build_dir,
            version_override=version,
            variant=variant,
        )

        # Output results
        if targets:
            for target in targets:
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
