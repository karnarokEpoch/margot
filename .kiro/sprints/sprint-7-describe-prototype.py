"""Reference prototype for the `describe` output design (Sprint 7, Item 3).

Not shipped code — no error handling for Item 1's load gate, no `domain`/`services`/
`commands` layering, no tests. It exists to make the layout in `sprint-7.md` and
`sprint-7-describe-sample.md` reproducible and to give whoever implements
`src/margot/domain/describe.py` / `src/margot/commands/describe.py` a working starting
point for the tree/panel construction instead of a blank file.

Regenerate the sample with:

    uv run --with rich --with pyyaml python \
        .kiro/sprints/sprint-7-describe-prototype.py path/to/app.yaml > out.txt

Known gaps against the real implementation this must close:
- No Item 1 load gate (missing file, bad YAML, wrong `kind`, unresolved Jinja2).
- No `--section` filtering.
- No `x-placeholder-extensions` on deployment profiles / components, only top-level.
- Domain logic (joins, component index) and rendering are mixed here; the real code
  splits them across `domain/describe.py` (pure) and `commands/describe.py` (rich).
"""

from pathlib import Path
import sys

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from yaml import safe_load

DASH = "\u2014"
DOT = " \u00b7 "
MISSING = Text(DASH, style="dim")


def literal(value: object) -> Text:
    """Render a scalar in literal form: strings quoted, numbers/bools bare, absent as em dash."""
    if value is None:
        return Text(DASH, style="dim")
    if isinstance(value, bool):
        return Text("true" if value else "false")
    if isinstance(value, (int, float)):
        return Text(str(value))
    if value == "":
        return Text('""')
    return Text(f'"{value}"')


def plain(value: object) -> Text:
    """Render a value without quoting (for key/value grids where quotes add noise)."""
    if value is None:
        return Text(DASH, style="dim")
    if isinstance(value, bool):
        return Text("true" if value else "false")
    return Text(str(value))


def kv(key: str, value: Text, width: int) -> Text:
    """Aligned 'key   value' leaf, key padded to width among its siblings."""
    line = Text(key.ljust(width), style="cyan")
    line.append(value)
    return line


def constraints(schema: dict) -> Text:
    """dataType followed by validation rules, joined with ' · ' in canonical order."""
    parts: list[str] = [str(schema.get("dataType", DASH))]

    lo, hi = schema.get("minValue"), schema.get("maxValue")
    if lo is not None and hi is not None:
        parts.append(f"{lo}..{hi}")
    elif lo is not None:
        parts.append(f"\u2265{lo}")
    elif hi is not None:
        parts.append(f"\u2264{hi}")

    lo, hi = schema.get("minLength"), schema.get("maxLength")
    if lo is not None and hi is not None:
        parts.append(f"{lo}..{hi} chars")
    elif lo is not None:
        parts.append(f"\u2265{lo} chars")
    elif hi is not None:
        parts.append(f"\u2264{hi} chars")

    if (rx := schema.get("regexMatch")) is not None:
        parts.append(f"re:{rx}")

    lo, hi = schema.get("minPrecision"), schema.get("maxPrecision")
    if lo is not None or hi is not None:
        parts.append(f"precision {lo if lo is not None else ''}..{hi if hi is not None else ''}")

    if (options := schema.get("options")) is not None:
        parts.append("one of: " + ", ".join(str(o) for o in options))
    if schema.get("multiselect"):
        parts.append("multi")
    if (empty := schema.get("allowEmpty")) is not None:
        parts.append(f"allowEmpty {'true' if empty else 'false'}")

    return Text(DOT.join(parts))


def identity_panel(doc: dict, source: str) -> Panel:
    meta = doc.get("metadata") or {}
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="cyan")
    grid.add_column()
    grid.add_column(style="cyan")
    grid.add_column()
    grid.add_row("id", plain(doc.get("id")), "version", plain(meta.get("version")))
    grid.add_row("name", plain(meta.get("name")), "", "")

    body: list = [grid, Text()]

    labels = Table.grid(padding=(0, 1))
    labels.add_column(style="bold")
    labels.add_column(overflow="fold")
    labels.add_row("Description:", plain(meta.get("description")))
    body.append(labels)

    catalog = meta.get("catalog")
    if not catalog:
        line = Text("Catalog: ", style="bold")
        line.append("None", style="dim")
        body.append(line)
        return Panel(Group(*body), title=str(doc.get("apiVersion", DASH)), subtitle=source)

    body.append(Text("Catalog:", style="bold"))
    app = catalog.get("application") or {}
    fields = ["tagline", "site", "icon", "descriptionFile", "licenseFile", "releaseNotes"]
    width = max(len(f) for f in [*fields, "organization"]) + 2

    cat = Table.grid(padding=(0, 0))
    cat.add_column(width=4)
    cat.add_column(style="cyan", width=width)
    cat.add_column(overflow="fold")
    for field in fields:
        cat.add_row("", field, plain(app.get(field)))

    tags = app.get("tags")
    cat.add_row("", "tags", Text(", ".join(tags)) if tags else MISSING)

    authors = catalog.get("author") or []
    rendered = [f"{a.get('name', DASH)} <{a['email']}>" if a.get("email") else str(a.get("name", DASH)) for a in authors]
    cat.add_row("", "author", Text(" · ".join(rendered)) if rendered else MISSING)

    orgs = catalog.get("organization") or []
    rendered = [f"{o.get('name', DASH)} {DASH} {o['site']}" if o.get("site") else str(o.get("name", DASH)) for o in orgs]
    cat.add_row("", "organization", Text(" · ".join(rendered)) if rendered else MISSING)

    body.append(cat)
    return Panel(Group(*body), title=str(doc.get("apiVersion", DASH)), subtitle=source)


def component_index(doc: dict) -> list[str]:
    """Distinct component names declared across all deployment profiles, in first-seen order."""
    seen: dict[str, None] = {}
    for profile in doc.get("deploymentProfiles") or []:
        for component in profile.get("components") or []:
            if (name := component.get("name")) is not None:
                seen.setdefault(name, None)
    return list(seen)


def profiles_panel(doc: dict) -> Panel:
    profiles = doc.get("deploymentProfiles") or []
    index = component_index(doc)
    title = f"Deployment profiles ({len(profiles)} profiles {DOT.strip()} {len(index)} components)"

    if not profiles:
        return Panel(Text("none", style="dim"), title=title)

    blocks: list = []
    for profile in profiles:
        root = Text(str(profile.get("type", DASH)), style="bold magenta")
        root.append("  ")
        root.append(str(profile.get("id", DASH)))
        tree = Tree(root)

        if (description := profile.get("description")) is not None:
            tree.add(Text(" ".join(description.split()), style="italic"))

        resources = profile.get("requiredResources") or {}
        labels = ["resources", "peripherals", "interfaces"]
        width = max(len(label) for label in labels) + 2

        parts: list[str] = []
        if (cpu := resources.get("cpu")) is not None:
            cores = f"cpu {cpu.get('cores', DASH)} cores"
            if architectures := cpu.get("architectures"):
                cores += f" ({', '.join(architectures)})"
            parts.append(cores)
        if (memory := resources.get("memory")) is not None:
            parts.append(f"memory {memory}")
        if (storage := resources.get("storage")) is not None:
            parts.append(f"storage {storage}")
        tree.add(kv("resources", Text(DOT.join(parts)) if parts else MISSING, width))

        if peripherals := resources.get("peripherals"):
            rendered = []
            for p in peripherals:
                detail = " ".join(str(p[k]) for k in ("manufacturer", "model") if p.get(k))
                rendered.append(f"{p.get('type', DASH)} ({detail})" if detail else str(p.get("type", DASH)))
            tree.add(kv("peripherals", Text(DOT.join(rendered)), width))

        if interfaces := resources.get("interfaces"):
            tree.add(kv("interfaces", Text(DOT.join(str(i.get("type", DASH)) for i in interfaces)), width))

        components = profile.get("components") or []
        branch = tree.add(Text("components", style="bold"))
        if not components:
            branch.add(Text("none", style="dim"))
        for component in components:
            leaf = branch.add(Text(str(component.get("name", DASH))))
            properties = component.get("properties") or {}
            if not properties:
                leaf.add(Text("none", style="dim"))
                continue
            pad = max(len(k) for k in properties) + 2
            for key, value in properties.items():
                leaf.add(kv(key, plain(value), pad))

        blocks.append(tree)

    interleaved: list = []
    for block in blocks:
        interleaved.extend([block, Text()])
    return Panel(Group(*interleaved[:-1]), title=title)


def configuration_panel(doc: dict) -> Panel:
    configuration = doc.get("configuration") or {}
    sections = configuration.get("sections") or []
    schemas = {s["name"]: s for s in configuration.get("schema") or [] if "name" in s}
    parameters = doc.get("parameters") or {}
    index = component_index(doc)
    total = len(index)

    count = sum(len(section.get("settings") or []) for section in sections)
    title = f"Configuration ({len(sections)} sections {DOT.strip()} {count} settings)"

    if not sections:
        return Panel(Text("none", style="dim"), title=title)

    referenced: set[str] = set()
    blocks: list = []

    for section in sections:
        root = Text(str(section.get("name", DASH)))
        root.append("  [Section]", style="dim")
        tree = Tree(root)

        for setting in section.get("settings") or []:
            leaf_label = Text(str(setting.get("name", DASH)), style="bold")
            leaf_label.append("  [Setting]", style="dim")
            if setting.get("immutable"):
                leaf_label.append("  immutable", style="yellow")
            leaf = tree.add(leaf_label)

            schema_name = setting.get("schema")
            schema_line = Text("Schema: ", style="cyan")
            schema_line.append(str(schema_name) if schema_name is not None else DASH)
            if schema_name in schemas:
                schema_line.append("  ")
                schema_line.append(constraints(schemas[schema_name]))
            elif schema_name is not None:
                schema_line.append("  (not defined)", style="dim")
            leaf.add(schema_line)

            parameter_name = setting.get("parameter")
            parameter_line = Text("Parameter: ", style="cyan")
            parameter_line.append(str(parameter_name) if parameter_name is not None else DASH)
            if parameter_name is not None and parameter_name not in parameters:
                parameter_line.append("  (not defined)", style="dim")
                leaf.add(parameter_line)
                continue

            referenced.add(parameter_name)
            branch = leaf.add(parameter_line)
            parameter = parameters.get(parameter_name) or {}

            default = Text("Default: ", style="cyan")
            default.append(literal(parameter.get("value")))
            branch.add(default)

            targets = parameter.get("targets") or []
            if not targets:
                branch.add(Text("no targets", style="dim"))
            for target in targets:
                components = target.get("components") or []
                pointer = Text("Pointer: ", style="cyan")
                pointer.append(literal(target.get("pointer")))
                pointer.append(f"  ({len(components)}/{total} components)", style="dim")
                node = branch.add(pointer)
                if not components:
                    node.add(Text("none", style="dim"))
                for component in components:
                    entry = Text(str(component))
                    if component not in index:
                        entry.append("  (not declared)", style="dim")
                    node.add(entry)

        blocks.append(tree)

    if orphans := [name for name in parameters if name not in referenced]:
        tree = Tree(Text(f"Unreferenced parameters ({len(orphans)})", style="bold yellow"))
        for name in orphans:
            node = tree.add(Text(name))
            default = Text("Default: ", style="cyan")
            default.append(literal((parameters[name] or {}).get("value")))
            node.add(default)
        blocks.append(tree)

    interleaved: list = []
    for block in blocks:
        interleaved.extend([block, Text()])
    return Panel(Group(*interleaved[:-1]), title=title)


def extensions_panel(doc: dict) -> Panel | None:
    extensions = doc.get("x-placeholder-extensions")
    if not extensions:
        return None
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="cyan")
    grid.add_column(overflow="fold")
    for key, value in extensions.items():
        grid.add_row(str(key), plain(value))
    return Panel(grid, title="Extensions")


def main() -> None:
    path = Path(sys.argv[1])
    doc = safe_load(path.read_text())
    console = Console(width=100, force_terminal=False, no_color=True, highlight=False)

    console.print(identity_panel(doc, str(path)))
    console.print()
    console.print(profiles_panel(doc))
    console.print()
    console.print(configuration_panel(doc))
    if (panel := extensions_panel(doc)) is not None:
        console.print()
        console.print(panel)


if __name__ == "__main__":
    main()
