# Sprint 8 — `describe` component-first view + orphan detection

**Goal:** Extend `margot describe`'s configuration display with a second traversal
direction, add read-only orphan/dead-end detection, and document shell completion setup.
No changes to `verify`, no new validation exit paths — everything here stays inside
`describe`'s existing contract (exit 0 always, except an unloadable descriptor).

**Prerequisite:** Sprint 7 merged. Reuses `domain/describe.py` dataclasses
(`Configuration`, `ConfigurationSection`, `Setting`, `Parameter`, `ParameterTarget`) and
the component index built in Sprint 7 for pointer ratios.

---

## Context

Sprint 7 shipped one traversal of the configuration block: **config-first** — section →
setting → schema/parameter → pointer → components. It answers "what can be configured,
and what validates it" — the order a reviewer thinks in when reading the spec top-down.

It does not answer the inverse question a reviewer asks when looking at a *component*:
"what parameters touch this component, and what setting/schema governs each one?" That
requires walking the same data backwards.

Sprint 7 also flagged, but deliberately deferred, "coherence observations" — parameters,
settings, or schemas that don't connect to anything. This sprint picks that up as orphan
detection.

---

## Scope

### Item 1 — Rename `config` section to `config-first`, add `component-first`

**Rename:** `--section config` → `--section config-first`. This is a breaking rename
(no deprecation alias) — `describe` is unreleased-stage tooling, not yet load-bearing for
external scripts. Update `canonical_order`, the default-render set, `_render_section`
dispatch, the docstring, `FEATURES.md`, and `ROADMAP.md`.

**Add:** `--section component-first` — same configuration data, walked from the other
end:

```text
component → parameter (via its pointer) → Setting: <name> → Schema: <name> <dataType> · <constraints>
```

**Display model (`domain/describe.py`):** new pure-transform function building a
component-indexed view from the existing `Configuration` dataclass — no new YAML
traversal, no new I/O. For each component in the component index:

1. Walk every `ConfigurationSection` → `Setting` → `Setting.parameter_resolved.targets[]`.
2. A target whose `components` includes this component is one edge: component →
   parameter name → (value/default) → owning setting → schema.
3. A component with no incoming targets at all renders with a dim `no parameters` line
   (same "faithful, not judgmental" rule Sprint 7 used for empty collections — see
   rich-rendering.md rule 4 on shallow trees).

Order components the same way the existing component index orders them (declaration
order across deployment profiles, deduplicated) — do not introduce a second ordering
rule.

**Rendering (`commands/describe.py`):** one tree per component, same panel container as
`config-first`, added as a new `elif` branch in `_render_section`. Follow rich-rendering
rule 4 — a schema's constraints ride on the setting's line, not their own level.

**Files:**
- `src/margot/domain/describe.py` — new dataclass(es) + builder function.
- `src/margot/commands/describe.py` — new tree builder + `_render_section` branch,
  `--section` help text, canonical order.
- `tests/unit/domain/test_describe.py` (or equivalent) — builder unit tests, no mocks.
- `tests/e2e/test_describe_cli.py` — extend the sensor-dashboard fixture assertions to
  cover `component-first`.
- `FEATURES.md`, `ROADMAP.md`.

### Item 2 — Orphan / dead-end detection

**Read-only for now** (locked decision) — this is a display concern, not a validation
gate. No exit code change, no `linkml` import, no new flag on `verify`. Surfaces inside
`describe`'s existing `extensions` section or a new dedicated section (open question
below).

**What counts as an orphan:**
- A `Parameter` with no `Setting` referencing it. (Already tracked today —
  `Configuration.unreferenced` — but only rendered inside `config-first`, not
  surfaced as its own concern.)
- A `Setting` whose `schema` reference does not resolve to any declared schema.
- A `Schema` declared but not referenced by any `Setting`.
- A `Parameter.targets[].components` entry naming a component that does not exist in the
  component index (dangling pointer — distinct from "unreferenced", this is a broken
  reference rather than an unused one).

**Open questions to settle before implementation:**
- Does this get its own `--section orphans` (consistent with the other sections,
  explicit opt-in like `extensions`), or does it fold into `config-first`/
  `component-first` as a trailing subtree the way `unreferenced` parameters already do?
  Leaning toward a dedicated section — orphans are a cross-cutting concern spanning both
  traversals, not naturally owned by either.
- Dangling component references: is this within scope for Sprint 8, or does it belong
  with `verify --remote`'s reachability work (Sprint 8 backlog item)? They're different
  questions — "does this pointer's target exist in the descriptor" vs. "does this OCI ref
  resolve" — but worth confirming they don't overlap in implementation.

**Files:**
- `src/margot/domain/describe.py` — orphan-collection builder(s), pure transform.
- `src/margot/commands/describe.py` — rendering.
- Unit + e2e tests, `FEATURES.md`.

### Item 3 — Document shell completion setup

`--install-completion` / `--show-completion` are Typer-provided today (visible in
`margot --help`) but have no dedicated how-to anywhere — they only appear verbatim inside
the copied help-text block in `README.md`.

**Confirmed via `margot --show-completion bash`:** neither flag takes a custom output
path. `--install-completion [bash|zsh|fish|powershell|pwsh]` appends directly to the
shell's default rc file (e.g. `~/.bashrc`) — no `--path` option, not appropriate for
anyone managing their own sourced-completions layout (e.g. a file under
`~/.bash_profile`-managed includes rather than a raw rc append).

Add a short "Shell completion" subsection (README and `docs/index.md`, kept in sync per
existing convention) documenting **both** paths, not just the one-liner:

```bash
# Quick setup — appends to your shell's rc file directly
margot --install-completion

# Manual setup — prints the script; redirect it wherever you source completions from
margot --show-completion bash > ~/.local/share/bash-completion/completions/margot
```

Note the shell-restart requirement for both, and that `--install-completion` offers no
control over *where* it writes — call this out explicitly so users who curate their own
rc includes reach for `--show-completion` first.

**Files:** `README.md`, `docs/index.md`.

---

## Out of scope (explicitly deferred)

- Minified JSON default output, `list`-style command, manifest recognition on `fetch`,
  more artifact types in `fetch`, `verify --remote` — all still backlog, untouched by
  this sprint. See `ROADMAP.md` Backlog / Stack.
- Turning orphan detection into a `verify` gate (exit 1 on findings) — explicitly
  deferred until read-only output has been reviewed.
- Deprecation alias for `--section config` — dropped outright, not aliased.
