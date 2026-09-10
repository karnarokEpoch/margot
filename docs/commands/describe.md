# margot describe

Render the Margo application description as a structured, visual view — rich panels, trees,
and tables. Read-only, no schema validation, no network.

```
margot describe [--project-dir PATH] [--manifest PATH]
                [--section metadata|profiles|config-first|component-first|extensions|orphans]
```

## Flags

| Flag | Default | Description |
|---|---|---|
| `--project-dir` | `.` | Directory holding `margo.yaml`. |
| `--manifest` | resolved from `margo.yaml` | Explicit `app.yaml` or `app.yaml.jinja` path. |
| `--section` | all default sections | Filter to one or more sections. Multiple `--section` flags are allowed. |

## Descriptor resolution

Identical to [`margot verify`](verify.md): `--manifest` if given, otherwise `margo.yaml`
`directory` → `app.yaml.jinja` (rendered to a temp file) or `app.yaml`. Never reads
`<build_dir>`, never requires a prior `build`.

## Sections rendered

Sections always appear in this order. `--section` filters which are shown; it never
reorders them.

### `metadata` — identity and catalog

`apiVersion` as the panel title, `id`, `metadata.version` and `metadata.name` as a grid,
the artifact OCI URI (`OCI: {repository}:{tag}`, or `OCI: None`), then `Description:` and
`Catalog:` blocks. Panel subtitle shows the resolved descriptor path, marked `(rendered)`
when from `app.yaml.jinja`.

### `profiles` — deployment profiles

One tree per profile: `type` and `id`, `description`, `requiredResources`, then
`components[]` → `properties`. Panel title shows a count (`7 profiles · 9 components`).

### `config-first` — configuration (default view)

A single tree walked top-down from configuration sections:

```
section → setting (+ immutable) → Schema: <name> <dataType> · <constraints>
                                → Parameter: <name> → Default: <value>
                                                    → Pointer: <p> (n/total)
                                                                 → components
```

Parameters that no `Setting` references appear in a trailing subtree. Panel title shows
a count (`6 sections · 22 settings`).

### `component-first` — components (not in default view)

An alternative configuration view walked component-first: each component lists its
incoming parameters (via their pointers) with their values, setting names, and schemas.
Useful for understanding what a specific component needs to configure.

Request with `--section component-first`.

### `extensions` — `x-placeholder-extensions`

Rendered only when present in the descriptor.

### `orphans` — coherence checks (not in default view)

Four categories of dangling or unreferenced descriptor elements:

- Unreferenced parameters: a `Parameter` not referenced by any `Setting`.
- Unresolved schema references: a `Setting` whose `schema` name doesn't resolve to a declared schema.
- Unreferenced schemas: a `Schema` declared but not referenced by any `Setting`.
- Dangling component references: a `Parameter.targets[].components` entry naming a component absent from all deployment profiles.

These are observations only — `describe` always exits 0. Use [`margot verify`](verify.md) for validation gates.

Request with `--section orphans`.

## Rendering notes

Values are rendered in literal form: strings quoted, numbers and booleans bare, `""` for
empty string, `—` for absent. Nothing is truncated or elided; long values word-wrap.

Descriptor text is escaped before printing, so `array[string]` and `[Container]` render
literally rather than being parsed as rich markup.

`type` and component `properties` keys are printed verbatim — no enum check, no fixed
property lookup. This is deliberate: margot supports `quadlet` profiles ahead of the
upstream spec, and the spec's property set is still in flux.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Always, even when orphans are found. |
| 1 | Descriptor cannot be loaded: missing, both `app.yaml` and `app.yaml.jinja` present, unresolved Jinja2 variable, unparseable YAML, or `kind` not `ApplicationDescription`. |

On exit 1, the error message points at `margot verify`.

## Example

```bash
# Describe the application descriptor in the current project
margot describe

# Show only the identity and deployment profiles
margot describe --section metadata --section profiles

# Show the component-first configuration view
margot describe --section component-first

# Show orphan/dead-end checks
margot describe --section orphans

# Describe a specific manifest file
margot describe --manifest path/to/app.yaml
```

See a real multi-component example: [Full example — Inspect with describe](../examples/full.md#inspect-with-describe).
