"""Package command: create offline bundles from built artifacts."""

from typing import Annotated

from typer import Option

from margot import console
from margot.domain.models import PackageType
from margot.services import package as package_service


def package_cmd(
    t: Annotated[
        list[str] | None,
        Option(
            "--type",
            "-t",
            help="Component type(s) to bundle: margo (default), compose, quadlet, bundle. Repeatable. "
            "Omit to bundle all found types.",
        ),
    ] = None,
    project_dir: Annotated[
        str,
        Option("--project-dir", help="Project directory containing margo.yaml (default: current directory)"),
    ] = ".",
    build_dir: Annotated[
        str,
        Option("--build-dir", help="Build output directory (default: .dist)"),
    ] = ".dist",
    output: Annotated[
        str | None,
        Option("--output", help="Output bundle path (default: .dist/<version>/<name>-<version>.tgz)"),
    ] = None,
) -> None:
    """Create offline bundle from built artifacts."""
    try:
        # Determine package type
        if not t:
            # No explicit type: bundle all found types
            package_type = PackageType.BUNDLE
        else:
            # Validate and expand types
            valid_types = ("margo", "compose", "quadlet", "bundle")
            for type_str in t:
                if type_str not in valid_types:
                    console.fatal(
                        f"invalid --type '{type_str}'. Must be one of: margo, compose, quadlet, bundle"
                    )

            if len(t) == 1 and t[0] == "bundle":
                package_type = PackageType.BUNDLE
            elif "bundle" in t:
                console.fatal("--type bundle cannot be combined with other types")
            else:
                # For explicit types (margo, compose, quadlet), we'd need to handle multiple
                # For now, keep it simple: one type at a time
                if len(t) > 1:
                    console.fatal("multiple --type values not supported; specify one type at a time")
                package_type = PackageType(t[0])

        # Call the service
        bundle_path = package_service.package(
            package_type,
            project_dir=project_dir,
            build_dir=build_dir,
            output=output,
        )

        console.success(f"Packaged: {bundle_path}")

    except ValueError as e:
        console.fatal(str(e))
