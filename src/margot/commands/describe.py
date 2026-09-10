"""Describe command: rich panel and tree rendering from display model.

This layer contains only rich object construction and no I/O. All values from the
domain model are passed through Text objects, never interpolated into markup strings.
All descriptor-derived values are escaped before rendering.
"""

from typing import Annotated, Any

from rich.console import Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from typer import Option

from margot import console
from margot.domain.describe import (
    Catalog,
    Configuration,
    ConfigurationSection,
    DeploymentProfile,
    Identity,
    OrphanReport,
    Parameter,
    Schema,
    Setting,
    build_catalog,
    build_component_first,
    build_configuration,
    build_deployment_profiles,
    build_identity,
    build_orphan_report,
    component_index,
)
from margot.services import describe as describe_service

DASH = "\u2014"  # em dash
DOT = " \u00b7 "  # middle dot with spaces


def _literal(value: object) -> Text:
    """Render a scalar in literal form: strings quoted, numbers/bools bare, absent as em dash."""
    if value is None:
        return Text(DASH, style="dim")
    if isinstance(value, bool):
        return Text("true" if value else "false")
    if isinstance(value, (int, float)):
        return Text(str(value))
    if value == "":
        return Text('""')
    # String: quote it
    escaped_str = escape(str(value))
    return Text(f'"{escaped_str}"')


def _plain(value: object) -> Text:
    """Render a value for display (no quotes, but escaped). For labels and unquoted values."""
    if value is None:
        return Text(DASH, style="dim")
    if isinstance(value, bool):
        return Text("true" if value else "false")
    escaped_str = escape(str(value))
    return Text(escaped_str)


def _kv_line(key: str, value: Text, width: int) -> Text:
    """Build a 'key   value' aligned line with key padded to width."""
    line = Text(key.ljust(width), style="cyan")
    line.append(value)
    return line


def _add_range_constraints(parts: list[str], schema: Schema, is_numeric: bool) -> None:
    """Add range constraints (minValue/maxValue or minLength/maxLength) to parts."""
    if is_numeric:
        if schema.min_value is not None and schema.max_value is not None:
            parts.append(f"{schema.min_value}..{schema.max_value}")
        elif schema.min_value is not None:
            parts.append(f"\u2265{schema.min_value}")
        elif schema.max_value is not None:
            parts.append(f"\u2264{schema.max_value}")
    elif schema.min_length is not None and schema.max_length is not None:
        parts.append(f"{schema.min_length}..{schema.max_length} chars")
    elif schema.min_length is not None:
        parts.append(f"\u2265{schema.min_length} chars")
    elif schema.max_length is not None:
        parts.append(f"\u2264{schema.max_length} chars")


def _constraint_format(schema: Schema) -> Text:
    """Format schema constraints in compact form: 1..65535, ≥10, ≤64, one of: a, b, c, etc."""
    parts: list[str] = []

    # minValue/maxValue range
    _add_range_constraints(parts, schema, is_numeric=True)

    # minLength/maxLength range
    _add_range_constraints(parts, schema, is_numeric=False)

    # Regex
    if schema.regex_match is not None:
        parts.append(f"re:{escape(schema.regex_match)}")

    # Precision
    if schema.min_precision is not None or schema.max_precision is not None:
        min_p = schema.min_precision if schema.min_precision is not None else ""
        max_p = schema.max_precision if schema.max_precision is not None else ""
        parts.append(f"precision {min_p}..{max_p}")

    # Options
    if schema.options:
        options_str = ", ".join(escape(str(o)) for o in schema.options)
        parts.append(f"one of: {options_str}")

    # Multiselect
    if schema.multiselect:
        parts.append("multi")

    # Allow empty
    if schema.allow_empty is not None:
        parts.append(f"allowEmpty {'true' if schema.allow_empty else 'false'}")

    return Text(DOT.join(parts))


def build_identity_catalog_panel(identity: Identity, catalog: Catalog | None, resolved_path: str, rendered: bool) -> Panel:
    """Build the identity+catalog panel.

    Title is apiVersion. Subtitle is resolved path, suffixed with (rendered) if templated.
    Grid shows id/version/name. OCI URI line follows. Description and Catalog follow.
    """
    subtitle = resolved_path + ("  (rendered)" if rendered else "")

    # Build body
    body: list = []

    # Build grid for id/version/name fields
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="cyan")
    grid.add_column()
    grid.add_column(style="cyan")
    grid.add_column()
    grid.add_row("id", _plain(identity.id), "version", _plain(identity.version))
    grid.add_row("name", _plain(identity.name), "", "")
    body.append(grid)
    body.append(Text())

    # OCI URI line
    if identity.oci_uri is None:
        oci_line = Text("OCI: ", style="bold")
        oci_line.append("None", style="dim")
        body.append(oci_line)
    else:
        oci_table = Table.grid(padding=(0, 1))
        oci_table.add_column(style="bold")
        oci_table.add_column(overflow="fold")
        oci_table.add_row("OCI:", _plain(identity.oci_uri))
        body.append(oci_table)

    # Description
    desc_table = Table.grid(padding=(0, 1))
    desc_table.add_column(style="bold")
    desc_table.add_column(overflow="fold")
    desc_table.add_row("Description:", _plain(identity.description))
    body.append(desc_table)

    # Catalog
    if catalog is None:
        cat_line = Text("Catalog: ", style="bold")
        cat_line.append("None", style="dim")
        body.append(cat_line)
    else:
        body.append(Text("Catalog:", style="bold"))
        cat_table = _build_catalog_table(catalog)
        body.append(cat_table)

    return Panel(
        Group(*body),
        title=_plain(identity.api_version).plain,
        subtitle=subtitle,
    )


def _build_catalog_table(catalog: Catalog) -> Table:
    """Build the catalog key-value table."""
    cat_table = Table.grid(padding=(0, 0))
    cat_table.add_column(width=4)
    cat_table.add_column(style="cyan", width=20)
    cat_table.add_column(overflow="fold")

    # Application fields
    if catalog.application:
        app = catalog.application
        app_fields = ["tagline", "site", "icon", "descriptionFile", "licenseFile", "releaseNotes"]
        for field in app_fields:
            value = getattr(app, field.replace("File", "_file"), None)
            cat_table.add_row("", field, _plain(value))

        # Tags
        tags_value = Text(DOT.join(escape(str(t)) for t in app.tags)) if app.tags else Text(DASH, style="dim")
        cat_table.add_row("", "tags", tags_value)

    # Author list
    if catalog.author:
        rendered_authors = []
        for a in catalog.author:
            if a.email:
                rendered_authors.append(f"{a.name} <{a.email}>")
            else:
                rendered_authors.append(str(a.name or DASH))
        author_text = Text(DOT.join(rendered_authors))
    else:
        author_text = Text(DASH, style="dim")
    cat_table.add_row("", "author", author_text)

    # Organization list
    if catalog.organization:
        rendered_orgs = []
        for o in catalog.organization:
            if o.site:
                rendered_orgs.append(f"{o.name} {DASH} {o.site}")
            else:
                rendered_orgs.append(str(o.name or DASH))
        org_text = Text(DOT.join(rendered_orgs))
    else:
        org_text = Text(DASH, style="dim")
    cat_table.add_row("", "organization", org_text)

    return cat_table


def build_deployment_profiles_panel(profiles: list[DeploymentProfile], index: list[str]) -> Panel:
    """Build the deployment profiles panel with tree structure.

    Title includes profile count and deduplicated component count.
    """
    title = f"Deployment profiles ({len(profiles)} profiles {DOT.strip()} {len(index)} components)"

    if not profiles:
        return Panel(Text("none", style="dim"), title=title)

    blocks: list = []
    for profile in profiles:
        # Profile root: type and id
        root_text = Text(_plain(profile.type).plain, style="bold magenta")
        root_text.append("  ")
        root_text.append(_plain(profile.id).plain)
        tree = Tree(root_text)

        # Description (italic, no markup)
        if profile.description:
            desc_text = Text(" ".join(escape(profile.description).split()), style="italic")
            tree.add(desc_text)

        # Components subtree
        components = profile.components or []
        comp_branch = tree.add(Text("components", style="bold"))
        if not components:
            comp_branch.add(Text("none", style="dim"))
        else:
            for component in components:
                comp_name = Text(escape(component.name or ""))
                comp_node = comp_branch.add(comp_name)
                props = component.properties or {}
                if not props:
                    comp_node.add(Text("none", style="dim"))
                else:
                    # Property key-value pairs
                    pad = max(len(k) for k in props) + 2
                    for key, value in props.items():
                        prop_line = _kv_line(key, _plain(value), pad)
                        comp_node.add(prop_line)

        blocks.append(tree)

    # Interleave blocks with blank lines
    interleaved: list = []
    for block in blocks:
        interleaved.extend([block, Text()])
    if interleaved:
        interleaved.pop()  # Remove trailing blank

    return Panel(Group(*interleaved), title=title)


def _build_schema_line(setting: Setting) -> Text:
    """Build the schema line for a setting."""
    schema_line = Text("Schema: ", style="cyan")
    if setting.schema:
        schema_line.append(escape(setting.schema.name or ""))
        schema_line.append("  ")
        schema_line.append(escape(setting.schema.data_type or ""))
        if setting.schema.data_type:
            schema_line.append("  ")
            schema_line.append(_constraint_format(setting.schema))
    else:
        schema_line.append(DASH, style="dim")
    return schema_line


def _build_parameter_line(setting: Setting) -> Text:
    """Build the parameter line with inline default value if present."""
    param_line = Text("Parameter: ", style="cyan")
    if setting.parameter:
        param_line.append(escape(setting.parameter))
        if setting.parameter_resolved:
            param_line.append("  ")
            param_line.append(_literal(setting.parameter_resolved.value))
    else:
        param_line.append(DASH, style="dim")
    return param_line


def _add_targets_to_node(param_node: Any, param: Parameter, total_components: int, index: list[str]) -> None:  # noqa: ANN401
    """Add targets and components to the param_node tree."""
    targets = param.targets or []
    if not targets:
        param_node.add(Text("no targets", style="dim"))
    else:
        for target in targets:
            pointer_line = Text("Pointer: ", style="cyan")
            pointer_line.append(_literal(target.pointer))
            n_components = len(target.components or [])
            pointer_line.append(f"  ({n_components}/{total_components} components)", style="dim")
            pointer_node = param_node.add(pointer_line)

            comps = target.components or []
            if not comps:
                pointer_node.add(Text("none", style="dim"))
            else:
                for comp_name in comps:
                    comp_text = Text(escape(comp_name))
                    if comp_name not in index:
                        comp_text.append("  (not declared)", style="dim")
                    pointer_node.add(comp_text)


def _build_section_tree(section: ConfigurationSection, total_components: int, index: list[str]) -> Tree:
    """Build the tree for a single configuration section with all its settings."""
    section_root = Text(escape(section.name or ""))
    section_root.append("  [Section]", style="dim")
    section_tree = Tree(section_root)

    for setting in section.settings:
        # Setting node
        setting_label = Text(escape(setting.name or ""), style="bold")
        setting_label.append("  [Setting]", style="dim")
        if setting.immutable:
            setting_label.append("  immutable", style="yellow")
        setting_node = section_tree.add(setting_label)

        # Add schema line
        schema_line = _build_schema_line(setting)
        setting_node.add(schema_line)

        # Add parameter line
        param_line = _build_parameter_line(setting)
        param_node = setting_node.add(param_line)

        # Add targets and components if parameter is resolved
        if setting.parameter_resolved:
            _add_targets_to_node(param_node, setting.parameter_resolved, total_components, index)

    return section_tree


def _build_unreferenced_tree(unreferenced: list[str]) -> Tree:
    """Build the tree for unreferenced parameters."""
    orphan_root = Text(f"Unreferenced parameters ({len(unreferenced)})", style="bold yellow")
    orphan_tree = Tree(orphan_root)
    for param_name in unreferenced:
        param_node = orphan_tree.add(Text(escape(param_name)))
        default_line = Text("Default: ", style="cyan")
        default_line.append(DASH, style="dim")
        param_node.add(default_line)
    return orphan_tree


def build_configuration_panel(config: Configuration, index: list[str]) -> Panel:
    """Build the configuration panel with configuration-first join tree.

    Title includes section count and setting count.
    """
    total_settings = sum(len(s.settings) for s in config.sections)
    title = f"Configuration ({len(config.sections)} sections {DOT.strip()} {total_settings} settings)"

    if not config.sections and not config.unreferenced:
        return Panel(Text("none", style="dim"), title=title)

    blocks: list = []
    total_components = len(index)

    # Build section trees
    for section in config.sections:
        section_tree = _build_section_tree(section, total_components, index)
        blocks.append(section_tree)

    # Build unreferenced parameters tree
    if config.unreferenced:
        orphan_tree = _build_unreferenced_tree(config.unreferenced)
        blocks.append(orphan_tree)

    # Interleave with blank lines
    interleaved: list = []
    for block in blocks:
        interleaved.extend([block, Text()])
    if interleaved:
        interleaved.pop()  # Remove trailing blank

    return Panel(Group(*interleaved), title=title)


def build_component_first_panel(config: Configuration, index: list[str]) -> Panel:
    """Build the component-first panel with component-indexed parameter edges.

    Title includes component count. Each component is a tree root with its incoming
    parameters as edges: parameter (via pointer) → Setting: <name> → Schema.

    Args:
        config: The Configuration dataclass.
        index: The component index (in declaration order).

    Returns:
        A Panel with the component-first view.
    """
    title = f"Components ({len(index)} components)"

    if not index:
        return Panel(Text("none", style="dim"), title=title)

    # Build the component-first view from domain layer
    component_first_view = build_component_first(config, index)

    blocks: list = []

    for comp_node in component_first_view.components:
        # Component root
        root_text = Text(escape(comp_node.name or ""), style="bold")
        root_text.append("  [Component]", style="dim")
        tree = Tree(root_text)

        if not comp_node.parameters:
            # No parameters targeting this component
            tree.add(Text("no parameters", style="dim"))
        else:
            # Build parameter edges
            for edge in comp_node.parameters:
                # Parameter line: parameter name → pointer
                param_line = Text(escape(edge.parameter_name or ""), style="bold")
                param_line.append("  ")
                param_line.append(_literal(edge.pointer))
                param_line.append("  [Parameter]", style="dim")
                param_node = tree.add(param_line)

                # Value line
                value_line = Text("Value: ", style="cyan")
                value_line.append(_literal(edge.value))
                param_node.add(value_line)

                # Setting line
                setting_line = Text("Setting: ", style="cyan")
                setting_line.append(escape(edge.setting_name or ""))
                param_node.add(setting_line)

                # Schema line (reuse the existing formatter)
                # Create a minimal Setting object for schema line formatting
                if edge.schema:
                    schema_line = Text("Schema: ", style="cyan")
                    schema_line.append(escape(edge.schema.name or ""))
                    schema_line.append("  ")
                    schema_line.append(escape(edge.schema.data_type or ""))
                    if edge.schema.data_type:
                        schema_line.append("  ")
                        schema_line.append(_constraint_format(edge.schema))
                    param_node.add(schema_line)

        blocks.append(tree)

    # Interleave with blank lines
    interleaved: list = []
    for block in blocks:
        interleaved.extend([block, Text()])
    if interleaved:
        interleaved.pop()  # Remove trailing blank

    return Panel(Group(*interleaved), title=title)


def build_extensions_panel(extensions: dict) -> Panel | None:
    """Build extensions panel when x-placeholder-extensions is present.

    Args:
        extensions: The x-placeholder-extensions mapping.

    Returns:
        A Panel, or None if extensions is None or empty.
    """
    if not extensions:
        return None

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="cyan")
    grid.add_column(overflow="fold")
    for key, value in extensions.items():
        grid.add_row(escape(str(key)), _plain(value))

    return Panel(grid, title="Extensions")


def build_orphans_panel(orphan_report: OrphanReport) -> Panel:  # noqa: PLR0912, PLR0915, C901
    """Build the orphans/dead-ends panel.

    Args:
        orphan_report: An OrphanReport dataclass from build_orphan_report.

    Returns:
        A Panel with the orphan report organized into four category subtrees.
    """
    total_orphans = (
        len(orphan_report.unreferenced_params)
        + len(orphan_report.unresolved_schema_refs)
        + len(orphan_report.unreferenced_schemas)
        + len(orphan_report.dangling_component_refs)
    )

    title = f"Orphans/dead-ends ({total_orphans} total)"

    if total_orphans == 0:
        return Panel(Text("none", style="dim"), title=title)

    blocks: list = []

    # 1. Unreferenced parameters
    unreferenced_root = Text("Unreferenced parameters", style="bold")
    unreferenced_root.append(f"  ({len(orphan_report.unreferenced_params)})", style="dim")
    unreferenced_tree = Tree(unreferenced_root)
    if not orphan_report.unreferenced_params:
        unreferenced_tree.add(Text("none", style="dim"))
    else:
        for param_name in orphan_report.unreferenced_params:
            unreferenced_tree.add(Text(escape(param_name)))
    blocks.append(unreferenced_tree)

    # 2. Unresolved schema references
    unresolved_root = Text("Unresolved schema references", style="bold")
    unresolved_root.append(f"  ({len(orphan_report.unresolved_schema_refs)})", style="dim")
    unresolved_tree = Tree(unresolved_root)
    if not orphan_report.unresolved_schema_refs:
        unresolved_tree.add(Text("none", style="dim"))
    else:
        for setting_name, schema_name in orphan_report.unresolved_schema_refs:
            line = Text(escape(setting_name))
            line.append("  ")
            line.append(DASH, style="dim")
            line.append("  ")
            line.append(escape(schema_name), style="yellow")
            unresolved_tree.add(line)
    blocks.append(unresolved_tree)

    # 3. Unreferenced schemas
    unreferenced_schemas_root = Text("Unreferenced schemas", style="bold")
    unreferenced_schemas_root.append(f"  ({len(orphan_report.unreferenced_schemas)})", style="dim")
    unreferenced_schemas_tree = Tree(unreferenced_schemas_root)
    if not orphan_report.unreferenced_schemas:
        unreferenced_schemas_tree.add(Text("none", style="dim"))
    else:
        for schema_name in orphan_report.unreferenced_schemas:
            unreferenced_schemas_tree.add(Text(escape(schema_name)))
    blocks.append(unreferenced_schemas_tree)

    # 4. Dangling component references
    dangling_root = Text("Dangling component references", style="bold")
    dangling_root.append(f"  ({len(orphan_report.dangling_component_refs)})", style="dim")
    dangling_tree = Tree(dangling_root)
    if not orphan_report.dangling_component_refs:
        dangling_tree.add(Text("none", style="dim"))
    else:
        for param_name, pointer, comp_name in orphan_report.dangling_component_refs:
            line = Text(escape(param_name))
            line.append("  ")
            line.append(_literal(pointer))
            line.append("  ")
            line.append(DASH, style="dim")
            line.append("  ")
            line.append(escape(comp_name), style="yellow")
            dangling_tree.add(line)
    blocks.append(dangling_tree)

    # Interleave with blank lines
    interleaved: list = []
    for block in blocks:
        interleaved.extend([block, Text()])
    if interleaved:
        interleaved.pop()  # Remove trailing blank

    return Panel(Group(*interleaved), title=title)


def _render_section(  # noqa: PLR0913
    section_name: str,
    identity: Identity,
    catalog: Catalog | None,
    profiles: list[DeploymentProfile],
    index: list[str],
    config: Configuration,
    descriptor_dict: dict,
    resolved_path: str,
    rendered: bool,
) -> None:
    """Render a single section panel based on section name."""
    if section_name == "metadata":
        panel = build_identity_catalog_panel(identity, catalog, resolved_path, rendered)
        console.print_renderable(panel)
    elif section_name == "profiles":
        panel = build_deployment_profiles_panel(profiles, index)
        console.print_renderable(panel)
    elif section_name == "config-first":
        panel = build_configuration_panel(config, index)
        console.print_renderable(panel)
    elif section_name == "component-first":
        panel = build_component_first_panel(config, index)
        console.print_renderable(panel)
    elif section_name == "extensions":
        extensions = descriptor_dict.get("x-placeholder-extensions")
        if extensions:
            panel = build_extensions_panel(extensions)
            if panel:
                console.print_renderable(panel)
    elif section_name == "orphans":
        orphan_report = build_orphan_report(config, index, descriptor_dict)
        panel = build_orphans_panel(orphan_report)
        console.print_renderable(panel)


# CLI command function
def describe_cmd(
    project_dir: str = Option(".", "--project-dir", help="Directory containing margo.yaml."),
    manifest: str | None = Option(None, "--manifest", help="Path to app.yaml or app.yaml.jinja."),
    section: Annotated[
        list[str] | None,
        Option(
            "--section",
            help="Render only this section (metadata|profiles|config-first|component-first|extensions|orphans). Repeatable.",
        ),
    ] = None,
) -> None:
    """Describe a Margo application description in rich, structured output.

    Renders the descriptor through panels and trees: identity+catalog, deployment profiles,
    configuration (sections → settings → schema/parameters → targets → components).
    """
    try:
        # Load descriptor with metadata and resolution info (temp file cleaned up after parsing)
        loaded = describe_service.load_descriptor(project_dir or ".", manifest)
        descriptor_dict = loaded.descriptor
        meta = loaded.meta
        resolved_path = loaded.source_path
        rendered = loaded.rendered
    except (ValueError, TypeError) as e:
        console.fatal(f"{e!s} Run 'margot verify' to debug.")

    # Build display model from dict, threading meta into build_identity for OCI URI
    identity = build_identity(descriptor_dict, meta)
    catalog = build_catalog(descriptor_dict)
    profiles = build_deployment_profiles(descriptor_dict)
    index = component_index(descriptor_dict)
    config = build_configuration(descriptor_dict)

    # Determine which sections to render
    requested_sections = set(section or []) if section else set()
    if not requested_sections:
        # All sections by default, but extensions and orphans only when present
        requested_sections = {"metadata", "profiles", "config-first"}
        if descriptor_dict.get("x-placeholder-extensions"):
            requested_sections.add("extensions")

    # Canonical order, regardless of flag order
    canonical_order = ["metadata", "profiles", "config-first", "component-first", "extensions", "orphans"]
    sections_to_render = [s for s in canonical_order if s in requested_sections]

    # Render sections
    for section_name in sections_to_render:
        _render_section(section_name, identity, catalog, profiles, index, config, descriptor_dict, resolved_path, rendered)
