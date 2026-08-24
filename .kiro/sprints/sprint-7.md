# Sprint 7 — `margot describe`

**Goal:** Ship `margot describe`: a read-only, purely visual view of a Margo application
description. It takes the raw `app.yaml` (or `app.yaml.jinja`, rendered) and organizes it
into rich panels, trees and tables so a human can review the whole descriptor at a glance
— the spirit of `kubectl describe`, but rendered with boxes and structure instead of
flat text.

**Prerequisite:** Sprint 6 merged. `describe` reuses the descriptor resolution function
(find → render → load) and `infra/templating.py` from `services/verify.py` unchanged.

---

## Division of labour with `verify`

| | `verify` | `describe` |
|---|---|---|
| Question answered | "Is this shippable?" | "What is in here?" |
| Audience | CI, scripts | human reviewer |
| Output | plain pass/fail lines | rich panels / trees / tables only |
| Exit code | 0 pass, 1 any error | 0 always, except an unloadable descriptor |
| Schemas | LinkML Schema A / B | none — no `linkml` import at all |

`--deep` was originally a `verify` flag; it was split out because a CI gate and a viewer
have nothing in common but the file they read.

**Decision (locked): no `--check` flag.** `describe` does not run LinkML and does not
report findings. Coherence observations (see Open questions) may arrive later, but no
validation is bolted onto this command in this sprint.

---

## Scope

### Item 1 — Descriptor loading (reuse, don't rebuild)

Call the Sprint 6 resolution function: `--manifest` if given, else `margo.yaml`
`directory` → `app.yaml.jinja` then `app.yaml`; a template is rendered to a temp file
with the same context and `StrictUndefined` behavior `build` uses. Never reads
`<build_dir>`, never requires a prior `build`.

**Decision (locked): refuse rather than degrade.** `describe` renders a descriptor that
loads, and nothing else. It fails with `console.fatal` pointing at `margot verify` when:

- the file is missing, or both `app.yaml` and `app.yaml.jinja` are present,
- Jinja2 rendering fails (unresolved variable),
- the YAML does not parse, or does not parse into a mapping,
- `kind` is not `ApplicationDescription`.

Past that gate, no edge-case handling: whatever the spec permits gets rendered as-is.
Missing optional fields render as `—`, empty collections render as an empty panel with a
dim "none" line. The **mess the Margo spec allows is exactly what this command shows** —
a parameter no `Setting` refers to, a component with no `repository`, a profile with zero
components. `describe` displays it faithfully; it does not judge it.

**Files:** `src/margot/services/describe.py`.

### Item 2 — Display model

Pure transformation from the loaded dict to display dataclasses. No I/O, no rich, no
linkml — unit-testable with zero mocks.

Field paths, verified against the upstream schema at commit `45f4359`:

- **Identity:** `id`, `apiVersion`, `kind` are top-level. `name`, `version`,
  `description` live under `metadata` (`description` is optional).
- **Catalog:** `metadata.catalog.application` (`tagline`, `site`, `icon`,
  `descriptionFile`, `licenseFile`, `releaseNotes`, `tags`), `metadata.catalog.author[]`
  (`name`, `email`), `metadata.catalog.organization[]` (`name`, `site`).
- **Deployment profiles:** `deploymentProfiles[]` with `type` (`helm` or `compose` only —
  the spec's `slots.type` pattern is `^(helm|compose)$`), `id`, `description`,
  `requiredResources` (`cpu`, `memory`, `storage`, peripherals, communication
  interfaces), and `components[]` → `name` + `properties`
  (`repository`, `revision`, `wait`, `timeout`, `packageLocation`, `keyLocation`).
  **There is no `quadlet` profile type in the Margo spec** — quadlet is a margot build
  target, not an application-description concept, and never appears here.
- **Parameters:** top-level `parameters` map (`map[string]Parameter`, the key is the
  `identifier`). Each has `value` (the default) and `targets[]` (`pointer` + `components[]`).
- **Configuration:** `configuration.sections[]` → `settings[]` (`parameter`, `name`,
  `description`, `immutable`, `schema`) and `configuration.schema[]` (`name`, `dataType`,
  plus subclass rules: `minLength`, `maxLength`, `regexMatch`, `minValue`, `maxValue`,
  `allowEmpty`, `multiselect`, `options`).
- **Extensions:** `x-placeholder-extensions` maps, allowed on `ApplicationDescription`,
  `DeploymentProfile` and `Component`.

**The join:** constraints are not inline on `Parameter`. Link a parameter to its rules via
`configuration.sections[].settings[]` — `setting.parameter` → parameter name,
`setting.schema` → `configuration.schema[].name`. A parameter with no matching `Setting`
shows `—` for data type and constraints; that absence is the signal, not an error.

**Files:** `src/margot/domain/describe.py`,
`tests/unit/test_domain_describe.py` (join, missing fields, orphan parameter, empty
collections).

### Item 3 — Visual rendering

`commands/describe.py` builds the rich layout from the display model and prints it
through `console`. No parsing, no file I/O in this layer.

```
╭───────────────────────── my-application ──────────────────────────╮
│  id  myapp        version  1.0.0        kind  ApplicationDescription│
│  Human-readable description of the application                     │
╰────────────────────────────────────────────────────────────────────╯

╭─ Catalog ───────────────────╮ ╭─ Required resources ──────────────╮
│ tagline    Does things      │ │ cpu       2 cores / amd64         │
│ site       https://…        │ │ memory    512Mi                   │
│ icon       —                │ │ storage   2Gi                     │
│ author     Jane <j@ex.com>  │ ╰───────────────────────────────────╯
╰─────────────────────────────╯

╭─ Deployment profiles ─────────────────────────────────────────────╮
│ compose                                                            │
│ ├── my-app                                                         │
│ │   ├── repository  public.ecr.aws/g2n4p2m7/margo                  │
│ │   ├── revision    1.0.0                                          │
│ │   └── wait        true (timeout 2m30s)                           │
│ └── sidecar → …                                                    │
╰────────────────────────────────────────────────────────────────────╯

╭─ Parameters ──────────────────────────────────────────────────────╮
│ name      default  dataType  constraints    targets                │
│ greeting  hello    string    minLength 1    GREETING → my-app      │
│ replicas  1        integer   1..10          replicaCount → my-app  │
╰────────────────────────────────────────────────────────────────────╯

╭─ Configuration layout ────────────────────────────────────────────╮
│ General                                                            │
│ ├── Greeting text      → greeting   (schema: text-basic)           │
│ └── Replica count      → replicas   (schema: int-range, immutable) │
╰────────────────────────────────────────────────────────────────────╯
```

Rich elements: `Panel` per block, `Columns`/`Group` for side-by-side blocks, `Tree` for
profiles → components → properties and sections → settings, `Table` for parameters, `rule`
between major blocks. The extensions panel is rendered only when the descriptor actually
carries `x-placeholder-extensions` — vendor extensions are exactly what a reviewer wants
to spot.

**No text output modes.** No `--json`, no `--yaml`, no plain fallback. Users who want the
raw document already have the file; users who want machine-readable output have `fetch`.

**Console:** add `print_renderable(renderable)` to `console.py` alongside the existing
`print_table` — this command prints four different rich types, so a single generic entry
point is the right addition (the Sprint 6 plan's `print_panel` is superseded).

**Files:** `src/margot/commands/describe.py`, `src/margot/console.py`,
`src/margot/main.py` (register command), `tests/e2e/test_describe_cli.py`.

### Item 4 — CLI wiring

```
margot describe [--project-dir PATH]
                [--manifest PATH]
                [--section metadata|profiles|parameters|config|extensions]
```

- `--project-dir` → `.` (where `margo.yaml` lives, same as `build` and `verify`).
- `--manifest` → unset; resolved as in Item 1.
- `--section` → repeatable; when omitted, all sections render in the order shown above.

Exit codes: 0 always, 1 only when the descriptor cannot be loaded (Item 1 gate).

---

## Layering and output rules

| Concern | Home |
|---|---|
| Display dataclasses + parameter/schema join | `domain/describe.py` (pure) |
| Resolve, render, load the descriptor | `services/describe.py`, delegating to the Sprint 6 resolver + `infra/templating.py` + `infra/filesystem.load_yaml` |
| Rich layout construction and printing | `commands/describe.py` via `console.print_renderable` |

- `services/describe.py` — `console.info` per step (descriptor resolved, rendered, loaded).
- `commands/describe.py` — `console.print_renderable` / `console.fatal` only.
- `domain/describe.py` — no `console` import (existing domain rule).
- No `linkml` import anywhere in this command's path.

---

## Definition of done

- [ ] `margot describe` renders all sections for a descriptor exercising every block
      (catalog, two profiles, required resources, ≥2 parameter data types, configuration
      sections, `x-placeholder-extensions`).
- [ ] A templated project (`app.yaml.jinja`, no `app.yaml` on disk) describes end to end
      without running `build` first.
- [ ] Unloadable descriptor (missing / unparseable / wrong `kind` / unresolved Jinja2
      variable) exits 1 with a message pointing at `margot verify`.
- [ ] A descriptor with an orphan parameter, a component without `repository`, and a
      profile with no components renders without error — the gaps are visible, not fatal.
- [ ] `--section` renders only the requested blocks.
- [ ] No `--json` / `--yaml` / plain-text mode exists.
- [ ] `uv run pytest` passes, coverage gate (90%) met.
- [ ] Layer rules hold: no file I/O in `commands/`, no rich outside `commands/`, no
      `linkml` in this command's path.
- [ ] `FEATURES.md` gains a `margot describe` section; `ROADMAP.md` updated.
- [ ] Commits, one per item group: `feat(describe): descriptor loading and display model`,
      `feat(describe): rich panel rendering and CLI wiring`,
      `chore(describe): polish, docs and roadmap closure`.

---

## Open questions

1. **Coherence observations.** There is appetite for surfacing "this looks off" signals
   that no schema can express — e.g. a parameter nothing references, a `targets[].components`
   entry naming a component that does not exist, a `Setting` pointing at a missing
   parameter or schema. Shape undecided: dim annotations in place, a trailing
   "Observations" panel, or a separate future command. **Not in this sprint's scope** —
   revisit once the display exists and the real descriptors show which signals matter.
2. **Terminal width.** Panels assume ~100 columns. Decide during implementation whether
   narrow terminals collapse `Columns` to stacked panels (likely) or truncate.
3. **Multi-descriptor input.** Out of scope: one descriptor per invocation.
