# margot verify

Validate the Margo application description (`app.yaml` or `app.yaml.jinja`) against the
upstream Margo spec schema, and optionally against margot's curated recommended schema.

```
margot verify [--project-dir PATH] [--manifest PATH]
              [--schema PATH] [--recommended-schema PATH]
              [--recommend | --only-recommend] [--strict]
```

!!! note
    `margo.yaml` is not validated by this command — it is margot's build anchor, not a
    Margo spec document.

## Flags

| Flag | Default | Description |
|---|---|---|
| `--project-dir` | `.` | Directory holding `margo.yaml`. |
| `--manifest` | resolved from `margo.yaml` | Explicit `app.yaml` or `app.yaml.jinja` path. |
| `--schema` | vendored Schema A | Override the upstream Margo spec schema. |
| `--recommended-schema` | vendored Schema B | Override the curated recommended schema. |
| `--recommend` | off | Run Schema B as a second pass, after Schema A. |
| `--only-recommend` | off | Run Schema B instead of Schema A. |
| `--strict` | off | Turn the Schema B lint pass into a hard contract — any finding fails the run. |

`--recommend` and `--only-recommend` are mutually exclusive. Passing both is rejected before
any validation runs (exit 1).

`--strict` has no effect without `--recommend` or `--only-recommend` — it emits a warning
and proceeds.

## Manifest resolution

`verify` never reads `<build_dir>` and never requires a prior `build`.

1. `--manifest` if given — may point at `app.yaml` or `app.yaml.jinja`.
2. Otherwise, `margo.yaml` is loaded from `--project-dir` and its `directory` field is
   searched for `app.yaml.jinja` (first), then `app.yaml`. Both present is an error;
   neither is an error.
3. A `.jinja` descriptor is rendered to a temporary file with Jinja2 `StrictUndefined`.
   The rendered file is what gets validated.

Both schema passes validate the same resolved file — the descriptor is never re-rendered.

## Schemas

### Schema A — upstream Margo spec

Vendored at `src/margot/schemas/application-description.linkml.yaml`, pinned to an
upstream draft commit. Overridable with `--schema`.

Validates with:

- `JsonschemaValidationPlugin(closed=True)` — no unexpected fields
- `RecommendedSlotsPlugin()` — warns on missing recommended fields
- `MaximumCardinalityPlugin` — enforce cardinality constraints

Any error fails the run. The pinned commit SHA is printed so results are never mistaken
for validation against a stable spec.

### Schema B — margot recommended

Vendored at `src/margot/schemas/margo-recommended.linkml.yaml`. Not loaded unless
`--recommend` or `--only-recommend` is passed. Overridable with `--recommended-schema`.

Schema B is standalone — it does not import Schema A and enforces the spec's required-field
set (`apiVersion`, `id`, `metadata`, `deploymentProfiles`, and the required chain beneath
them) as its own ERRORs, so a Schema A re-vendor never silently changes what Schema B
reports.

## Behaviour matrix

| Flags | Schema A runs | Schema B runs | Exit code driven by |
|---|---|---|---|
| (none) | yes | no | Schema A errors |
| `--strict` | yes | no | Schema A errors (`--strict` warns it has nothing to act on) |
| `--recommend` | yes | yes | Schema A errors — Schema B is advisory |
| `--recommend --strict` | yes | yes | Schema A errors **or** any Schema B finding |
| `--only-recommend` | no | yes | nothing — always 0 |
| `--only-recommend --strict` | no | yes | any Schema B finding |
| `--recommend --only-recommend` | — | — | rejected, exit 1 |

## Output

Plain CI-check-style pass/fail lines, pipeable into CI logs.

- **Default (no `--recommend`):** the draft-spec line and the Schema A verdict.
- **`--recommend` with findings:** one labeled section per schema, each with its own verdict,
  then the overall `verify: PASS` / `verify: FAIL` line.
- **`--recommend` with both schemas clean:** no section headers — the output reads exactly
  like a clean default run.
- **`--only-recommend`:** Schema B findings and verdict only. No draft-spec line.

For visual inspection of a descriptor's structure, use [`margot describe`](describe.md).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Validation passed. |
| 1 | Schema A error, Schema B finding (with `--strict`), mutually exclusive flags, or descriptor cannot be resolved. |

## Example

```bash
# Validate against the Margo spec (default)
margot verify

# Validate with the recommended schema as an advisory second pass
margot verify --recommend

# Validate with the recommended schema only, fail on any finding
margot verify --only-recommend --strict

# Validate a specific manifest file
margot verify --manifest path/to/app.yaml

# Validate in a different project directory
margot verify --project-dir ../other-app
```
