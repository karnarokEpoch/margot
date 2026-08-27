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
A missing optional scalar renders as `—`. An absent nested block inside a panel collapses
to a single dim `<Block>  None` line — this is how a missing `metadata.catalog` renders.
An empty top-level collection still gets its own panel, with a dim `none` line inside.
The **mess the Margo spec allows is exactly what this command shows** —
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
- **Deployment profiles:** `deploymentProfiles[]` with `type`, `id`, `description`,
  `requiredResources` and `components[]` → `name` + `properties`.
  - `requiredResources` is **per profile**, not global: `cpu` (an object — `cores` as a
    decimal, `architectures[]` from `CpuArchitectureType`), `memory` and `storage`
    (binary-unit strings), `peripherals[]` (`type`, `manufacturer`, `model`) and
    `interfaces[]` (`type`).
  - **`type` is rendered verbatim, never validated.** Upstream `slots.type` currently
    pins `^(helm|compose)$`, but margot supports `quadlet` regardless — the upstream
    quadlet profile proposal is in flight and spells the value `quadlet.v1` (and helm as
    `helm.v3`). `describe` is not the place to police an enum that is actively moving.
  - **`properties` keys are iterated, not looked up.** At upstream HEAD
    `ComponentProperties` is `repository`, `revision`, `wait`, `timeout` — the
    `packageLocation` / `keyLocation` pair listed in earlier drafts of this sprint is not
    at HEAD, and the quadlet proposal reintroduces `packageLocation`. Rendering whatever
    keys the mapping actually carries, in document order, makes the display immune to
    this churn.
- **Parameters:** top-level `parameters` map (`map[string]Parameter`, the key is the
  `identifier`). Each has `value` (the default) and `targets[]` (`pointer` + `components[]`).
  Parameters are **not** a block of their own — they are reached through configuration
  (see the join below).
- **Configuration:** `configuration.sections[]` → `settings[]` (`parameter`, `name`,
  `description`, `immutable`, `schema` — `parameter` and `schema` are both required
  upstream) and `configuration.schema[]` (`name`, `dataType`, plus subclass rules:
  `minLength`, `maxLength`, `regexMatch`, `minValue`, `maxValue`, `minPrecision`,
  `maxPrecision`, `allowEmpty`, `multiselect`, `options`). `options` is a flat list of
  strings. `dataType` is a free string, documented as one of `string`, `integer`,
  `double`, `boolean` or their `array[...]` forms.
- **Extensions:** `x-placeholder-extensions` maps, allowed on `ApplicationDescription`,
  `DeploymentProfile` and `Component`.

**The join is configuration-first, and it is the heart of this command.** Configuration is
the only entry point into parameters; there is no separate parameters block. One traversal
produces the whole tree:

```text
configuration.sections[]                       → section
  └── settings[]                               → setting  (+ immutable flag)
      ├── setting.schema  → configuration.schema[].name    → dataType + constraints
      └── setting.parameter → parameters[<name>]           → default value
          └── targets[]                        → pointer
              └── components[]                 → component names
```

Two derived values the raw document does not contain:

- **Component index.** The set of component names declared across
  `deploymentProfiles[].components[].name`, **deduplicated**. For the sensor-dashboard
  descriptor that is 9 names from 11 entries — `sensor-dashboard-compose-simple` and
  `sensor-dashboard-quadlet-simple` each appear in two profiles. The denominator of the
  per-pointer ratio is this deduplicated count, because `targets[].components` references
  a *name*, and one name is one referent no matter how many profiles reuse it.
- **Unreferenced parameters.** Parameters that no `Setting` names. With no parameters
  table left, these would otherwise vanish from the output entirely — so they render as a
  trailing subtree of the configuration panel. Faithfulness to the descriptor requires
  it: the whole point is that the gaps stay visible.

A `Setting` whose `parameter` or `schema` names something absent renders the name followed
by a dim `(not defined)` — a statement of fact about the document, not a verdict.

**Files:** `src/margot/domain/describe.py`,
`tests/unit/test_domain_describe.py` (the section → setting → parameter → pointer →
components join, the deduplicated component index and per-pointer ratio, unreferenced
parameters, a setting naming a missing parameter or schema, missing fields, empty
collections).

### Item 3 — Visual rendering

`commands/describe.py` builds the rich layout from the display model and prints it
through `console`. No parsing, no file I/O in this layer.

Full rendered output against the real `sensor-dashboard` descriptor
(`margo/margo.yaml`: 7 profiles, 11 component entries / 9 distinct names, 22 parameters,
22 settings in 6 sections) is in
[`sprint-7-describe-sample.md`](sprint-7-describe-sample.md) — that is the acceptance
target for the e2e test, not the excerpt this section used to inline.

Rich elements: `Panel` per block, `Group` to compose a panel's interior, `Tree` for
profiles → components → properties and for the whole configuration traversal. The
extensions panel is rendered only when the descriptor actually carries
`x-placeholder-extensions` — vendor extensions are exactly what a reviewer wants to spot.

**Locked layout decisions:**

- **Three panels, not five.** Identity+catalog, deployment profiles, configuration — plus
  extensions when present. **There is no parameters panel.** Parameters are reached
  through configuration, which is the structure a reviewer actually thinks in: *what can
  be configured* → *what validates it* → *what value it defaults to* → *where it lands*.
  A flat parameters table restated the same facts in a second, disconnected shape.
- **All panels are full-width and stacked. No `Columns`.** No width threshold to tune.
  This closes the terminal-width open question.
- **The `apiVersion` is the identity panel's title.** `kind` is not rendered at all: the
  Item 1 load gate refuses anything whose `kind` is not `ApplicationDescription`, so
  printing it carries no information. `id`, `version` and `name` form the grid;
  `Description:` and `Catalog:` are labeled blocks below it.
- **The identity panel carries the catalog.** When `metadata.catalog` is absent the block
  collapses to `Catalog: None` — no empty sub-panel.
- **The panel subtitle is the resolved descriptor path**, suffixed `(rendered)` when it
  came from `app.yaml.jinja`. For a templated project the reviewer is looking at a temp
  file; which descriptor was resolved is the context that makes the rest legible.
- **Panel titles carry counts** — `(7 profiles · 9 components)`,
  `(6 sections · 22 settings)`. Cheap to compute, and it is the first thing a reviewer
  wants from a 700-line descriptor.
- **`requiredResources` is rendered inside its profile subtree**, never as a top-level
  panel — it is a per-profile field and seven profiles carry seven sets.
  `cpu`/`memory`/`storage` collapse to a single ` · `-joined `resources` line;
  `peripherals` and `interfaces` get their own sibling lines only when non-empty.
- **Per-pointer component ratio** `(n/total)`: `n` is the number of names listed in that
  `target.components`, `total` is the deduplicated component index from Item 2. A name
  not in the index is still counted in `n` and rendered with a dim `(not declared)` — so
  `(12/9)` is a possible and highly informative output, not a bug.
- **`immutable` is a dim tag on the `[Setting]` line**, not a child node — it is one bit
  and does not deserve a tree level. Rendered only when true.
- **Schema rules ride on the `Schema:` line**, not as children: `Schema: <name>  <dataType>
  · <constraints>`. This keeps the tree at six levels instead of seven.
- **Scalar values render in literal form** — strings quoted, numbers and booleans bare,
  empty string as `""`, absent as `—`. `Default: 1883` and `Default: "1883"` are
  different facts about the descriptor and must not look alike.
- **All descriptor-derived text is escaped before printing.** Rich interprets `[...]` as
  markup, and `array[string]` is a documented `dataType` value — an unescaped descriptor
  would silently swallow it. Style is applied via `Text` objects, never by interpolating
  document values into a markup string.
- **Nothing is ever truncated or elided.** Rich word-wraps instead. A folded repository
  URL is reviewable; an elided one is not. (`→ …` in the samples above marks *this sketch*
  eliding a subtree for brevity, not the command doing so.)
- **Constraint formatting** is compact and joined with ` · ` (never `,` — `options`
  values contain commas): `1..65535`, `≥10`, `≤64` for `minValue`/`maxValue`;
  `1..64 chars`, `≥1 chars`, `≤64 chars` for `minLength`/`maxLength`;
  `re:<pattern>` for `regexMatch`; `precision 2..4` for `minPrecision`/`maxPrecision`;
  `one of: a, b, c` for `options`; `multi` when `multiselect`. `allowEmpty` renders as
  the raw `allowEmpty false` — upstream's field description ("if true, indicates a value
  must be provided") contradicts the field name, and `describe` does not paraphrase a
  semantic it cannot pin down.
- **`type` and `properties` keys print as they appear in the document.** No enum check on
  `type`, no fixed property lookup — see Item 2. The real descriptor uses
  `type: quadlet`.

**No text output modes.** No `--json`, no `--yaml`, no plain fallback. Users who want the
raw document already have the file; users who want machine-readable output have `fetch`.

**Console:** add `print_renderable(renderable)` to `console.py` alongside the existing
`print_table` — this command prints several different rich types, so a single generic entry
point is the right addition (the Sprint 6 plan's `print_panel` is superseded).

**Files:** `src/margot/commands/describe.py`, `src/margot/console.py`,
`src/margot/main.py` (register command), `tests/e2e/test_describe_cli.py`.

**Reference material — not shipped code, do not import:**
[`sprint-7-describe-prototype.py`](sprint-7-describe-prototype.py) implements this
layout end to end against a real descriptor and produced
[`sprint-7-describe-sample.md`](sprint-7-describe-sample.md), the acceptance target. It
mixes domain logic and rendering in one file with no error handling — a starting point
for the tree/panel construction, not a template for the layering. Splitting it into
`domain/describe.py` (pure — the joins, the component index, the constraint/scalar
formatting) and `commands/describe.py` (rich construction only) is part of the
implementation work, not already done.

### Item 4 — CLI wiring

```text
margot describe [--project-dir PATH]
                [--manifest PATH]
                [--section metadata|profiles|config|extensions]
```

- `--project-dir` → `.` (where `margo.yaml` lives, same as `build` and `verify`).
- `--manifest` → unset; resolved as in Item 1.
- `--section` → repeatable; when omitted, all blocks render.
- **`--section` filters which blocks appear, it never reorders them.** Blocks always
  render in the canonical order above (metadata → profiles → config → extensions), so
  `--section config --section metadata` and `--section metadata --section config` produce
  identical output. The display model therefore carries no ordering state from the CLI
  layer.
- `metadata` selects the identity panel **including the catalog** — they are one panel,
  so there is no separate `catalog` value.
- **There is no `parameters` value**: parameters live inside `config`. On a descriptor the
  size of `sensor-dashboard` the configuration tree is a few hundred lines, which is
  precisely why per-block selection exists.

Exit codes: 0 always, 1 only when the descriptor cannot be loaded (Item 1 gate).

---

## Layering and output rules

| Concern | Home |
|---|---|
| Display dataclasses, the configuration-first join, component index | `domain/describe.py` (pure) |
| Resolve, render, load the descriptor | `services/describe.py`, delegating to the Sprint 6 resolver + `infra/templating.py` + `infra/filesystem.load_yaml` |
| Rich layout construction and printing | `commands/describe.py` via `console.print_renderable` |

- `services/describe.py` — `console.info` per step (descriptor resolved, rendered, loaded).
- `commands/describe.py` — `console.print_renderable` / `console.fatal` only.
- `domain/describe.py` — no `console` import (existing domain rule).
- No `linkml` import anywhere in this command's path.

---

## Definition of done

- [ ] `margot describe` renders every block for the real `sensor-dashboard` descriptor
      (`/home/louis/work/margo/sensor-app/margo/margo.yaml`) — 7 profiles, 22 settings in
      6 sections, absent `author`, `type: quadlet` — as the reference fixture.
- [ ] The configuration tree walks section → setting → schema/parameter → pointer →
      components, and each pointer shows `(n/total)` against the **deduplicated** component
      index (9 for the reference descriptor, not the 11 raw entries).
- [ ] No parameters panel exists; `--section parameters` is not a valid value.
- [ ] Parameters no `Setting` references appear in a trailing "unreferenced parameters"
      subtree — they are never silently dropped.
- [ ] A setting naming a missing parameter or schema renders `(not defined)`; a target
      naming an undeclared component renders `(not declared)`. Neither is fatal.
- [ ] A value containing rich markup characters (e.g. a `dataType` of `array[string]`)
      renders literally — descriptor text is escaped, never interpreted as markup.
- [ ] `Default: 1883` and `Default: "1883"` render differently; `""` and absent render as
      `""` and `—`.
- [ ] A templated project (`app.yaml.jinja`, no `app.yaml` on disk) describes end to end
      without running `build` first, and the panel subtitle shows the resolved path
      marked `(rendered)`.
- [ ] Unloadable descriptor (missing / unparseable / wrong `kind` / unresolved Jinja2
      variable) exits 1 with a message pointing at `margot verify`.
- [ ] A component without `repository` and a profile with no components render without
      error, and `type` is printed verbatim for `quadlet` / `quadlet.v1`.
- [ ] A descriptor with no `metadata.catalog` renders `Catalog: None` inside the identity
      panel rather than an empty panel.
- [ ] `--section` renders only the requested blocks, always in canonical order regardless
      of flag order.
- [ ] No `--json` / `--yaml` / plain-text mode exists.
- [ ] No `Columns` in the layout — every panel is full-width and stacked; long values
      wrap rather than truncate.
- [ ] `uv run pytest` passes, coverage gate (90%) met.
- [ ] Layer rules hold: no file I/O in `commands/`, no rich outside `commands/`, no
      `linkml` in this command's path.
- [ ] `FEATURES.md` gains a `margot describe` section; `ROADMAP.md` updated.
- [ ] Commits, one per item group: `feat(describe): descriptor loading and display model`,
      `feat(describe): rich panel rendering and CLI wiring`,
      `chore(describe): polish, docs and roadmap closure`.

---

## Open questions

1. **Coherence observations.** Partly delivered by the v3 design: the per-pointer
   `(n/total)` ratio, `(not declared)` on a target naming an unknown component,
   `(not defined)` on a setting naming a missing parameter or schema, and the
   unreferenced-parameters subtree all surface "this looks off" without judging it — they
   are arithmetic and set membership, not validation. What remains open is whether these
   also deserve a summarising **Observations** panel, and whether anything stronger
   (severity, exit code) belongs in a future command. **Still out of scope here** — the
   in-place signals ship first, the summary can follow once real descriptors show which
   ones matter.
2. ~~**Terminal width.**~~ **Closed.** No `Columns` anywhere — all panels are full-width
   and stacked, values wrap rather than truncate. Nothing depends on a column count.
3. **Multi-descriptor input.** Out of scope: one descriptor per invocation.
4. **Quadlet profile naming.** margot supports a quadlet deployment profile ahead of the
   upstream spec. The in-flight upstream proposal spells the value `quadlet.v1` (and helm
   as `helm.v3`), while `docs/examples/full.md` currently emits `quadlet`. `describe` is
   unaffected — it prints `type` verbatim — but `build`'s template context and the docs
   need to agree on one spelling. Decide outside this sprint.
