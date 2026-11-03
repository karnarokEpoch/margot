"""margot install: place one quadlet deployment profile of a Margo application on this host.

Files go to ``$XDG_CONFIG_HOME/containers/systemd/<application-id>/`` and systemd reloads them.
The command never starts, enables or stops a unit. It prints the systemctl commands for the user.
"""

from typing import Annotated

from oras.auth import AuthenticationException
from requests.exceptions import RequestException
from rich.console import Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from typer import Argument, Option

from margot import console
from margot.domain.install import InstallPlan, SourceRecord
from margot.domain.install_parameters import parse_set_options
from margot.infra import systemd
from margot.infra.credentials import CredentialsExpiredError
from margot.infra.install_store import quadlet_root
from margot.infra.oci import OciRegistryError
from margot.services import install as install_service
from margot.services.install import InstallResult, PreparedInstall

_REGISTRY_ERRORS = (AuthenticationException, CredentialsExpiredError, OciRegistryError, PermissionError, RequestException)
_DOT = " · "
_LABEL_WIDTH = 12


def install_cmd(  # noqa: PLR0913 - one parameter per documented option
    uri: str | None = Argument(None, help="OCI reference of a margo artifact (oci:// optional). Selects the remote source."),
    project_dir: str | None = Option(None, "--project-dir", help="Built project directory (default: current directory)."),
    build_dir: str | None = Option(None, "--build-dir", help="Build output directory for project mode (default: .dist)."),
    profile: str | None = Option(None, "--profile", help="Deployment profile id to install."),
    yes: bool = Option(False, "--yes", "-y", help="Do not ask for confirmation."),
    dry_run: bool = Option(False, "--dry-run", help="Show the plan and change nothing on this host."),
    set_values: Annotated[
        list[str] | None,
        Option(
            "--set",
            metavar="NAME=VALUE",
            help="Value for a parameter of the profile's components (repeatable; the last value wins).",
        ),
    ] = None,
) -> None:
    """Install one quadlet deployment profile of a Margo application on this host.

    Use a built project, a pulled static folder, or a remote OCI artifact. Files are placed in
    ~/.config/containers/systemd/<application-id>/ and systemd reloads them. install does not start
    anything: it prints the systemctl commands to run.
    """
    if uri is not None and (project_dir is not None or build_dir is not None):
        console.fatal(
            "A URI and --project-dir/--build-dir are mutually exclusive: install a remote artifact or a local project.",
            code=2,
        )
    if not dry_run and not yes and not console.is_interactive():
        console.fatal(
            "No terminal to ask for confirmation. Pass --yes to install, or --dry-run to only show the plan.",
            code=2,
        )
    if build_dir is not None and install_service.detect_source(uri, project_dir) != "project":
        console.fatal("--build-dir applies to a built project only, not to a URI or a static folder.", code=2)

    overrides = _parse_set_values(set_values or [])
    prepared = _prepare(uri, project_dir, build_dir, profile, overrides)
    try:
        _show_plan(prepared.plan)
        if dry_run:
            console.print_renderable(Text("Dry run: nothing was changed on this host."))
            return
        if not yes and not console.confirm(f"Install {len(prepared.plan.components)} component(s) on this host? [y/N]"):
            console.fatal("Aborted: nothing was installed", code=1)
        _report(_apply(prepared))
    finally:
        prepared.cleanup()


def _parse_set_values(values: list[str]) -> dict[str, str]:
    """Parse --set NAME=VALUE before any work. A malformed value is a usage error (exit 2)."""
    try:
        overrides, repeated = parse_set_options(values)
    except ValueError as error:
        console.fatal(escape(str(error)), code=2)
    for name in repeated:
        console.warning(escape(f"--set {name} is given more than once; the last value is used."))
    return overrides


def _prepare(
    uri: str | None,
    project_dir: str | None,
    build_dir: str | None,
    profile: str | None,
    overrides: dict[str, str],
) -> PreparedInstall:
    try:
        return install_service.prepare_install(
            uri=uri,
            project_dir=project_dir,
            build_dir=build_dir,
            profile_id=profile,
            overrides=overrides,
        )
    except _REGISTRY_ERRORS as error:
        console.fatal(escape(str(error)), code=4)
    except (ValueError, TypeError) as error:
        console.fatal(escape(str(error)), code=3)
    except Exception as error:  # noqa: BLE001
        console.fatal(escape(f"Install failed: {error}"), code=1)


def _apply(prepared: PreparedInstall) -> InstallResult:
    try:
        return install_service.apply_install(prepared, root=quadlet_root())
    except systemd.SystemdError as error:
        console.fatal(escape(str(error)), code=1)
    except (ValueError, TypeError) as error:
        console.fatal(escape(str(error)), code=3)
    except OSError as error:
        console.fatal(escape(f"Install failed while writing files: {error}"), code=1)


def _show_plan(plan: InstallPlan) -> None:
    console.print_renderable(Panel(Group(*_plan_rows(plan), _component_tree(plan)), title="Install plan", title_align="left"))
    if plan.bindings:
        console.print_table(_parameter_table(plan))
    hint = "Hint: install does not schema-validate the descriptor; run `margot verify` first."
    console.print_renderable(Text(hint, style="dim"))
    if plan.unapplied:
        names = ", ".join(plan.unapplied)
        console.warning(escape(f"Parameter(s) without a value are not applied: {names}. Set one with --set NAME=VALUE."))


def _parameter_table(plan: InstallPlan) -> Table:
    """Parameter · value · source · variable · units, one row per target (sprint-13 §3.5, §3.9)."""
    services = {component.entry.name: component.services for component in plan.components}
    table = Table(title=f"Parameters ({len(plan.parameters)} applied)", title_justify="left")
    for header in ("parameter", "value", "source", "variable", "units"):
        table.add_column(header, overflow="fold")
    for binding in plan.bindings:
        table.add_row(
            Text(binding.parameter),
            Text(binding.value),
            Text(binding.source),
            Text(binding.variable),
            Text(_DOT.join(services.get(binding.component, ()))),
        )
    return table


def _plan_rows(plan: InstallPlan) -> list[Text]:
    return [
        _row("application", plan.app_id),
        _row("name", f"{plan.app_name}{_DOT}{plan.app_version}"),
        _row("profile", f"{plan.profile_id}{_DOT}quadlet"),
        _row("source", _source_text(plan.source)),
        _row("target", plan.target_dir),
    ]


def _source_text(source: SourceRecord) -> str:
    detail = source.uri if source.uri is not None else source.path or ""
    return f"{source.kind}{_DOT}{detail}"


def _row(label: str, value: str) -> Text:
    line = Text(f"{label:<{_LABEL_WIDTH}}", style="dim")
    line.append(value)
    return line


def _component_tree(plan: InstallPlan) -> Tree:
    root = Tree(Text(f"Components ({len(plan.components)})"))
    for component in plan.components:
        node = root.add(Text(f"{component.entry.name}{_DOT}{component.reference}"))
        node.add(Text(f"archive sha256 {component.entry.archive_sha256}", style="dim"))
        node.add(Text("files: " + _DOT.join(component.entry.files)))
        node.add(Text("services: " + _DOT.join(component.services) if component.services else "services: none"))
    return root


def _report(result: InstallResult) -> None:
    console.success(f"Installed {len(result.services)} unit(s) into:")
    console.print_line(str(result.app_dir))
    console.print_renderable(Group(*_next_steps(result)))


def _next_steps(result: InstallResult) -> list[Text]:
    """The commands and timing notes margot prints. It never runs them (sprint-13 §3.7)."""
    lines = [Text("Next steps. install did not start anything; run these yourself:", style="bold")]
    if result.start_services:
        for service in result.start_services:
            lines.append(Text(f"  systemctl --user start {service}"))
            lines.append(Text(f"  systemctl --user status {service}"))
    else:
        lines.append(Text("  No container or pod unit to start. Other units start as dependencies."))
    lines.extend(
        Text(
            f"{service} starts at the next login/boot. Without a login, boot starts it only with lingering "
            "(loginctl enable-linger).",
            style="dim",
        )
        for service in result.wanted_services
    )
    if result.upgraded and result.start_services:
        lines.append(Text("Running services keep the old unit files until restarted. Restart them with:", style="bold"))
        lines.extend(Text(f"  systemctl --user restart {service}") for service in result.start_services)
    lines.append(
        Text(
            "A first start may pull images and exceed systemd's 90 s start timeout.",
            style="dim",
        )
    )
    if result.parameters:
        lines.append(
            Text(
                "Parameter values are visible through: systemctl --user show -p Environment <service>, "
                "or systemctl --user cat <service>.",
                style="dim",
            )
        )
    return lines
