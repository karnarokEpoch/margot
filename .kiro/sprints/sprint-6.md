# Sprint 6 — `margot verify`

**Goal:** Ship a complete `margot verify` command: local-only LinkML validation against
the upstream Margo spec schema (always-on) and an opt-in (`--recommend`) margot-curated
recommended schema, plus an opt-in (`--deep`) structured rich display of the full
`app.yaml` state. Default output (no flags) is plain CI-check-style pass/fail. Remote
artifact reachability checking is descoped to the backlog (see `ROADMAP.md`).

**Subject under verification:** the Margo **application description** — `app.yaml`, or
`app.yaml.jinja` when the project templates it. `margo.yaml` is *not* validated by this
command: it is the build anchor for margot's own artifacts, not a Margo spec document.
When the descriptor is a Jinja2 template, `verify` renders it to a temporary file (same
context as `build`) and validates the rendered result. See Item 3.

**Prerequisite:** Sprint 5 must be merged. `id` field is in `margo.yaml`, `domain/metadata.py`
is final, and the Jinja2 build path is stable.

---

## Background: two LinkML schemas

**Schema A — upstream Margo spec (baseline):**
`https://github.com/margo/specification/blob/45f4359d129c1f04532d17b358d6f50eaa3ca62f/src/specification/applications/application-description.linkml.yaml`

This is the normative schema from the Margo project. It defines what is structurally
required for a valid `app.yaml`. Validation against it is the hard gate: failures here
mean the artifact will be rejected by a Margo-compliant runtime.

**Schema B — margot recommended schema (curated, stricter):**
A schema authored and maintained in this repo under `schemas/margo-recommended.linkml.yaml`.
It extends or overlays Schema A with:
- Recommended-but-not-required fields flagged as warnings.
- Stricter cardinality constraints.
- Margot-specific conventions (e.g. presence of icon, release notes, description file).

**Design:** the two schemas are separate validation passes. Schema A failures are errors
(exit 1). Schema B is a **lint pass by default** — findings are reported, exit stays 0
whatever their severity. With `--strict`, Schema B becomes a **contract** — any finding
fails the run (exit 1). The output labels each finding clearly with its source schema.
The precise LinkML-severity → `ValidationFinding.severity` mapping is settled at the
start of Phase 3, with the Schema B authoring spike (see Item 2).

---

## Layering and output rules

Resolves where each piece lives, so the layer table in `FEATURES.md` and the console
rules in `code-conventions.md` still hold once `verify` lands.

| Concern | Home | Notes |
|---|---|---|
| `Severity`, `ValidationFinding`, `VerifyResult`, display models | `domain/validation.py` | Pure dataclasses + the `parameters` ↔ `configuration.schema` join. No I/O, no linkml, no rich. Unit-testable with zero mocks. |
| Jinja2 rendering of `app.yaml.jinja` | `infra/templating.py` | Extracted from `services/build.py` (`_build_margo`) so `build` and `verify` share one implementation. `services/` never imports `services/`. |
| Reading YAML, writing the rendered temp file | `infra/filesystem.py` | New `load_yaml(path)` and `write_temp_text(text, suffix)` helpers next to `copy_tree` / `make_tarball`. |
| LinkML invocation | `validation/linkml_runner.py` | The **only** module allowed to import `linkml`. Returns `list[ValidationFinding]`. |
| Finding → text/rows | `validation/error_formatter.py` | Returns plain strings and row tuples. No `rich` objects, no printing. |
| Orchestration | `services/verify.py` | Resolves the manifest, renders if needed, calls `validation/`, builds the display model via `domain/validation.py`, returns `VerifyResult`. No rich, no printing beyond `console.info`. |
| Rendering | `commands/verify.py` | Builds `rich` `Table` / `Panel` objects from `VerifyResult` and prints them through `console`. No parsing, no file I/O. |

Console rules for the new code:

- `services/verify.py` — `console.info` per significant step (manifest resolved, rendered
  to temp, Schema A run, Schema B run).
- `validation/` — `console.debug` per schema load / validation call. Never `success`,
  `warning`, or a rich object; it is an adapter, not an output layer.
- `commands/verify.py` — `console.success` / `console.warning` / `console.fatal` only,
  plus `console.print_table` and a new `console.print_panel(panel)` added to
  `console.py` mirroring the existing `print_table`.
- `domain/validation.py` — must not import `console` (existing domain rule).

---

## Build phases

The five scope items below are implemented in **four sequential phases**, not as one
batch. Each phase is its own PR and its own commit, and must leave `verify` in a working
state — this lets Schema A ship and be useful before Schema B content exists.

Commit messages (one per phase, Angular convention):

- Phase 1 — `feat(verify): LinkML validation against vendored Margo spec schema`
- Phase 2 — `feat(verify): --deep structured display and full CLI flags`
- Phase 3 — `feat(verify): recommended schema and --recommend wiring`
- Phase 4 — `chore(verify): --strict polish, edge cases, docs and roadmap closure`

**Phase 1 — Schema A only, minimal command.**
Vendor Schema A (Item 2, Schema A part only), extract Jinja2 rendering into
`infra/templating.py` and add the `load_yaml` / `write_temp_text` helpers (Item 3,
manifest resolution), build `validation/linkml_runner.py` + `error_formatter.py`
(Item 1) and `domain/validation.py` findings, then wire a minimal `margot verify` that
runs Schema A only and prints plain pass/fail (Item 3 + a minimal slice of Item 5 — no
`--recommend`, no `--deep` yet). Definition of "done" for this phase: `margot verify`
correctly validates a rendered `app.yaml` against the real upstream schema end to end,
and `build` still passes its existing tests after the rendering extraction.

**Phase 2 — Display layer.**
Add `--deep` structured display (Item 4 in full), the `domain/validation.py` display
models and parameter join, `console.print_panel`, and finish CLI flag wiring for
everything except `--recommend`/Schema B (rest of Item 5). `verify` now has its full
default-vs-`--deep` behavior, still Schema A only.

**Phase 3 — Schema B authoring + integration.**
Start with the Schema B mechanism spike (see Item 2), then author
`margo-recommended.linkml.yaml` content (remainder of Item 2) and wire `--recommend`
into `services/verify.py` and the command output (remainder of Item 3 and Item 5) —
including the A/B section separator requirement.

**Phase 4 — Polish and DoD closure.**
`--strict` behavior, LinkML plugin set review (see Item 1 — drop any plugin that proves
unusable rather than shipping it broken), edge cases (Schema A clean + `--recommend`
clean → no stray B section), full e2e test pass, `FEATURES.md` `verify` section and
`ROADMAP.md` update, final commit.

---



### Item 1 — `validation/` infrastructure

Create the missing validation layer from `FEATURES.md`.

**Files to create:**
- `src/margot/validation/__init__.py` — empty.
- `src/margot/validation/linkml_runner.py` — run LinkML validation against a schema file.
  Wrap `linkml.validator` with `JsonschemaValidationPlugin(closed=True)`,
  `RecommendedSlotsPlugin()`, and `MaximumCardinalityPlugin`. Return a structured result
  list, not raw LinkML types — callers should not import linkml directly.

  **Clarification:** this is a dependency-boundary concern, not a claim that margot
  reshapes what LinkML can report. We still fully depend on `linkml.validator` for the
  actual validation logic and cannot change what it finds — the upstream schema
  (`application-description.linkml.yaml`) is one large `ApplicationDescription` root
  with nested classes (`Metadata`, `DeploymentProfile`, `Parameter`, `Configuration`,
  etc.), so most findings will legitimately be "one big object, many nested errors."
  The wrapper's only job is to map LinkML's report objects into margot's own
  `ValidationFinding(field_path, message, severity)` dataclass (defined in
  `domain/validation.py`) so `commands/verify.py` and `error_formatter.py` never import
  `linkml` types directly (see layer rule in `AGENTS.md`). No per-field special-casing
  beyond what LinkML already reports.

  **Plugin set is provisional.** Two known unknowns, both accepted as tune-after-
  implementation rather than up-front spikes: (a) whether the installed `linkml` version
  ships `MaximumCardinalityPlugin` at all, (b) whether `closed=True` false-fails on the
  spec's open `x-placeholder-extensions` map (declared on `ApplicationDescription`,
  `DeploymentProfile`, and `Component`). Wire all three plugins, exercise them against a
  descriptor that uses vendor extensions, and **drop any plugin that misbehaves before
  the release** — do not ship a validator that rejects spec-valid input.
- `src/margot/validation/error_formatter.py` — format findings into plain strings and row
  tuples (`field_path`, `message`, `severity`). Returns data, never `rich` objects and
  never prints; `commands/verify.py` owns rendering (see Layering and output rules).
- `src/margot/validation/max_cardinality.py` — `MaximumCardinalityPlugin` implementation
  (if not provided by the installed linkml version; otherwise a thin re-export).

**Dependency:** `linkml` — add to `pyproject.toml`.

**Tests:**
- `tests/unit/validation/__init__.py` — required, tests are packages in this repo.
- `tests/unit/validation/test_linkml_runner.py` — run against a minimal fixture schema
  and a known-good / known-bad YAML. Covers: all-pass, single error, warning-only.
- `tests/unit/validation/test_error_formatter.py` — format a mock finding; check row
  shape and severity labels.
- `tests/unit/test_domain_validation.py` — `ValidationFinding` / `VerifyResult` and the
  parameter-join display builder, no mocks.

---

### Item 2 — Bundled schemas

**Schema A (upstream):** fetched at build/install time or downloaded on first use.

**Decision needed before implementation:** choose one:
- **(a) Vendored at install time:** copy the upstream YAML into `src/margot/schemas/` as
  `application-description.linkml.yaml`. Pin to the commit in the filename or a
  `SCHEMA_VERSION` constant. Update manually when the spec bumps.
- **(b) Downloaded on first `verify` run:** fetch from the canonical GitHub URL, cache
  under `~/.config/margot/schemas/`. Requires network on first use, but always fetchable.

**Decision (locked):** option (a) — vendored. Avoids a network dependency in the critical
validation path; pinned commit guarantees reproducibility. The schema URL and commit SHA
are recorded in a comment at the top of the vendored file.

**Draft-spec messaging:** the Margo specification is still in draft, so the pinned commit
is not a stable release. `margot verify` output must state which commit/version of the
upstream schema it validated against (e.g. a line like
`Validated against Margo spec (draft, commit 45f4359)`), so results are never mistaken
for validation against a final/stable spec. Emit it from `commands/verify.py` with
`console.success` — it is part of the check result, not a log line, and must stay visible
without `--verbose`/`--debug` (`console.info` is suppressed by default, see
`code-conventions.md`).

**Schema B (recommended):** lives in `src/margot/schemas/margo-recommended.linkml.yaml`.

**Mechanism spike (Phase 3, before authoring content):** "extends or overlays Schema A"
is not a LinkML primitive. Decide between (a) a separate schema that `imports:` the
vendored Schema A file — needs a distinct `id`/`name` and import-path resolution through
the `importlib.resources` directory, or (b) a standalone schema that redeclares only the
classes it constrains via `slot_usage`. Prototype the chosen option against a real
descriptor before writing any recommendation content.

Content TBD in implementation, but must at minimum cover (paths verified against the
upstream schema at commit `45f4359`):
- `metadata.description` present and non-empty.
- `metadata.catalog.application.icon`, `.descriptionFile`, `.releaseNotes` flagged as
  `RecommendedSlots`.
- `metadata.catalog.author` present (spec marks it optional).
- At least one `deploymentProfiles[]` entry, each with at least one `components[]` entry.

OCI-level annotations (`org.opencontainers.image.title` and friends) are **out of scope
for Schema B** — they are artifact metadata written by `push`, not fields of the
application description.

**Files:**
- `src/margot/schemas/application-description.linkml.yaml` — vendored upstream schema.
- `src/margot/schemas/margo-recommended.linkml.yaml` — curated stricter schema.
- `src/margot/schemas/__init__.py` — empty; expose `SCHEMA_A_PATH`, `SCHEMA_B_PATH`
  constants (resolved via `importlib.resources`).

---

### Item 3 — `services/verify.py`

**Decision (locked): local-only for Sprint 6.** No `--remote` flag, no `OrasClient` call,
no network dependency in this command. `verify` validates the local `app.yaml` against
Schema A and Schema B and stops there. Remote artifact reachability checking (originally
step 4-7 below) is moved to the backlog — see `ROADMAP.md`.

Orchestrates the verification flow. Returns a structured result — no rich output here.

```
verify(
    project_dir: str = ".",                       # where margo.yaml lives
    manifest_path: str | None = None,             # explicit app.yaml / app.yaml.jinja
    schema_path: str | None = None,               # override Schema A
    recommended_schema_path: str | None = None,   # override Schema B
    recommend: bool = False,                      # enable Schema B (see Item 5)
    strict: bool = False,                         # Schema B becomes a contract
) -> VerifyResult
```

`VerifyResult` dataclass (in `domain/validation.py`):
```
schema_a_results: list[ValidationFinding]
schema_b_results: list[ValidationFinding]   # empty when recommend=False
display: VerifyDisplay | None               # populated for --deep, None if load failed
schema_a_version: str                       # pinned draft commit, for the output line
passed: bool
```

`ValidationFinding`: `field_path`, `message`, `severity` (ERROR / WARNING / INFO).

**Manifest resolution (locked):** `verify` operates on the *source* descriptor and never
requires a prior `build`, never reads `<build_dir>` (`.dist` by default).

1. If `--manifest` is given, use it as-is — it may point at an `app.yaml` or an
   `app.yaml.jinja`.
2. Otherwise load `margo.yaml` from `project_dir`, take `meta.directory` (same resolution
   `build` uses) and look inside `<project_dir>/<meta.directory>/` for `app.yaml.jinja`,
   then `app.yaml`. Both present → error with the same message `build` raises
   (`services/build.py`: "Both app.yaml.jinja and app.yaml found ..."). Neither present →
   error.
3. If the resolved file is a `.jinja` template, render it through `infra/templating.py`
   with `build_jinja2_context(meta, global_repository=meta.repository)` and
   `StrictUndefined` — byte-for-byte the same rendering `build` performs — and write the
   result to a **temporary file** via `infra/filesystem.write_temp_text`. Validate that
   temp file. Report its path with `console.debug`; delete it when done.
4. An unresolved Jinja2 variable is a `verify` failure with the same message shape as
   `build` ("Unresolved Jinja2 variable in app.yaml.jinja: ...").
5. A YAML parse failure on the resolved/rendered file is a Schema A hard failure — no
   Schema B pass, no `--deep` display.

**Local validation flow:**
1. Resolve and (if templated) render the descriptor per above.
2. Run Schema A validation → `schema_a_results`. Any ERROR → `passed = False`.
3. If `recommend=True`, run Schema B validation → `schema_b_results`. Without `strict`
   this is a lint pass: findings are reported and `passed` is untouched. With `strict`
   it is a contract: any finding → `passed = False`. If `recommend=False`,
   `schema_b_results` stays empty and Schema B is not run at all.

**Files:**
- `src/margot/services/verify.py`
- `src/margot/infra/templating.py` — Jinja2 rendering extracted from `services/build.py`.
- `tests/integration/test_verify.py` — good, bad (A), bad (B) with `recommend=True`,
  strict mode, `app.yaml.jinja` rendered from a temp project tree, both-files-present
  error, unresolved-placeholder error.

**Backlog (not in this sprint):** remote artifact reachability check (`--remote`) —
tracked in `ROADMAP.md`. Original design: for each component with a version/tag in
`margo.yaml`, call `OrasClient.get_manifest(ref)`, report REACHABLE / MISSING /
WRONG_TYPE, with `check_credentials(hostname)` before each call.

---

### Item 4 — Parameter inspection display

**Decision (locked): plain by default, `--deep` for structured display.**

- **Default (no flag):** simple CI-check style output — pass/fail lines, no panels, no
  tree. Suitable for piping into CI logs. This is the existing `success` / `warning` /
  `fatal` line-based output already used elsewhere (see `code-conventions.md`), not a new
  format.
- **`--deep` flag:** enables the structured rich display described below (panels for
  Application / Components / Parameters). This is the "structured tree representation"
  originally described as always-on — it is now opt-in.

When `--deep` is passed and the descriptor passes structural validation, display a
structured summary of the file's content to support visual review. This is a rich
rendering of the parsed artifact, not a second validation pass.

**What to display (only with `--deep`).** Field paths below are verified against the
upstream schema at commit `45f4359` — `id`/`apiVersion`/`kind` are top-level, everything
else descriptive lives under `metadata`:

```
┌─ Application ──────────────────────────────────────────┐
│ id          myapp              (top-level id)          │
│ name        My Application     (metadata.name)         │
│ version     1.0.0              (metadata.version)      │
│ description Human-readable …   (metadata.description)  │
└─────────────────────────────────────────────────────────┘

┌─ Deployment profiles ──────────────────────────────────┐
│ profile  component   repository                revision │
│ compose  my-app      public.ecr.aws/g2n4p2m7/…  1.0.0   │
│ helm     my-chart    public.ecr.aws/g2n4p2m7/…  1.0.0   │
└─────────────────────────────────────────────────────────┘

┌─ Parameters ───────────────────────────────────────────┐
│ name           default   dataType  constraints         │
│ greeting       hello     string    minLength 1         │
│ replicas       1         integer   1..10               │
│ debug.enabled  false     boolean   —                   │
└─────────────────────────────────────────────────────────┘
```

Profile rows come from `deploymentProfiles[].components[]`: `type` on the profile
(`helm` or `compose` — the spec's `slots.type` pattern is `^(helm|compose)$`), then
`component.name`, `component.properties.repository`, `component.properties.revision`.
**There is no `quadlet` profile type in the Margo spec** — quadlet is a margot build
target, not an application-description concept, so it never appears in these panels.
`metadata.description` is optional in the spec; render `—` when absent.

The parameters table is parsed from the top-level `parameters` map (confirmed against the
upstream schema: `ApplicationDescription.parameters` is a `map[string]Parameter`, NOT
nested under `deploymentProfiles` — the open question in this doc about the exact path is
resolved). Each `Parameter` has `name` (also the map key, it is the `identifier`), `value`
(the default), and `targets`. Validation constraints (`minLength`, `maxLength`,
`regexMatch`, `minValue`, `maxValue`, `options`, …) are NOT inline on `Parameter` — they
live under `Configuration.schema` as `Schema` subclass objects keyed by `name`, linked
back to a parameter only indirectly via `configuration.sections[].settings[]`
(`setting.parameter` → param name, `setting.schema` → schema name). The parameters panel
performs that join; if no matching `Setting`/`Schema` exists for a parameter, show the
default value with `—` for `dataType` and constraints.

**Implementation note:** building the display model is separate from LinkML validation.
`services/verify.py` loads the YAML through `infra/filesystem.load_yaml` and hands the
dict to a pure builder in `domain/validation.py` (which owns the join logic and is
unit-tested without mocks). Only runs when `--deep` is passed.

**Files:**
- `src/margot/domain/validation.py` — `VerifyDisplay`, `ApplicationSummary`,
  `ProfileRow`, `ParameterRow` and the join. Pure, no I/O.
- `src/margot/commands/verify.py` — renders panels from `VerifyResult.display` only when
  `--deep` is set. Without `--deep`, prints plain pass/fail lines via `console.success` /
  `console.warning` / `console.fatal`. Panels are skipped when `display is None` (i.e.
  the descriptor could not be parsed).
- `src/margot/console.py` — add `print_panel(panel)` alongside the existing `print_table`.

---

### Item 5 — `commands/verify.py` and CLI wiring

```
margot verify [--project-dir PATH]
              [--manifest PATH]
              [--schema PATH]
              [--recommended-schema PATH]
              [--recommend]
              [--strict]
              [--deep]
```

`--remote`, `--version`, `--registry`, `--repository` are removed from this sprint's
scope (see Item 3 decision) — tracked in `ROADMAP.md` backlog instead.

Defaults:
- `--project-dir` → `.` (where `margo.yaml` lives, same as `build`).
- `--manifest` → unset; resolved from `margo.yaml` `directory` as
  `<project-dir>/<directory>/app.yaml.jinja` or `.../app.yaml` (Item 3). Templates are
  rendered to a temp file before validation.
- `--schema` → vendored Schema A path.
- `--recommended-schema` → vendored Schema B path.
- `--recommend` → off. Schema A always runs; Schema B does not run at all unless
  `--recommend` is passed (locked decision for Item 5 — see Background section note
  below).
- `--strict` → off. Only meaningful with `--recommend`: turns the Schema B lint pass into
  a contract. Passing `--strict` without `--recommend` is a no-op and must emit a
  `console.warning`.
- `--deep` → off. Plain CI-check-style pass/fail output by default (Item 4).

**Decision (locked) — Schema B default behavior:** Schema B is opt-in via `--recommend`,
not always-on-but-silent. When Schema A is run alone (default) and it produces no
findings, there must be no Schema B noise. When `--recommend` is passed and both schemas
produce findings, output must clearly separate them with a labeled section per schema
(e.g. a header/divider `── Schema A (Margo spec) ──` / `── Schema B (recommended) ──`)
so a reader never has to guess which schema a finding came from.

Output structure (always shown in this order):
1. The draft-spec line — `Validated against Margo spec (draft, commit <sha>)` via
   `console.success`.
2. Schema A results (nothing but the pass line if all pass; full findings if any fail).
   Plain lines by default, table if `--deep`.
3. Schema B results — only shown at all if `--recommend` was passed. When shown, always
   under its own clearly labeled section, separated from Schema A's section.
4. Application / Deployment profiles / Parameters panels — only if `--deep` and the
   descriptor parsed successfully.
5. Final pass/fail line.

Exit codes: 0 = passed, 1 = any error. Schema B findings only affect the exit code with
`--strict`.

**Files:**
- `src/margot/commands/verify.py`
- `src/margot/main.py` — register `verify` command.
- `tests/e2e/test_verify_cli.py` — CLI smoke tests: missing manifest, valid, invalid
  (Schema A), templated descriptor (`app.yaml.jinja`) rendered and validated,
  `--recommend` warnings (Schema B), `--recommend` + `--strict`, `--strict` without
  `--recommend` (warning, no behavior change), `--deep` display, default (no flags) plain
  output, Schema A clean + `--recommend` clean (no stray B section).

---

## Definition of done

- [ ] All five items implemented (Item 3 local-only, no `--remote`).
- [ ] `uv run pytest` passes with no failures, coverage gate (90%) still met.
- [ ] Jinja2 rendering extracted to `infra/templating.py` and shared by `build` and
      `verify`; existing `build` tests unchanged and passing.
- [ ] A templated project (`app.yaml.jinja`, no `app.yaml` on disk) verifies end to end
      without running `build` first.
- [ ] Vendored schema file present, schema version constants declared, and the draft-spec
      commit line is printed by default via `console.success`.
- [ ] `margo-recommended.linkml.yaml` has at minimum the fields listed in Item 2, and only
      runs when `--recommend` is passed.
- [ ] Without `--strict`, Schema B findings never change the exit code; with `--strict`,
      any Schema B finding exits 1.
- [ ] Default (no flags) output is plain pass/fail, no panels, no tables.
- [ ] `--deep` renders the Application / Deployment profiles / Parameters panels correctly
      for a descriptor with at least two parameter data types.
- [ ] `--recommend` output clearly separates Schema A and Schema B findings under
      distinct labeled sections.
- [ ] Every LinkML plugin still wired is one that does not false-fail on a spec-valid
      descriptor using `x-placeholder-extensions`; any plugin that misbehaves is removed
      before release.
- [ ] Layer rules hold: `linkml` imported only in `validation/linkml_runner.py`, no rich
      objects outside `commands/`, no file I/O in `commands/verify.py`.
- [ ] No `# TODO` markers left from this sprint's work.
- [ ] `FEATURES.md` `verify` section matches the shipped command (flags, manifest
      resolution, output).
- [ ] `ROADMAP.md` updated: Sprint 6 items moved to Completed Sprints table; `--remote`
      check added to backlog (Remaining commands section).
- [ ] Four commits, one per phase, with the messages listed in Build phases.

---

## Open questions to resolve at sprint start

All resolved, with two items deliberately deferred to the phase that needs them:

1. **Schema A vendoring vs download-on-demand:** ~~confirm before starting Item 2~~ —
   **resolved: vendored (option a)**, plus draft-spec version messaging (see Item 2).
2. **`margo-recommended.linkml.yaml` content:** minimum set listed in Item 2. The
   overlay mechanism (import vs standalone `slot_usage`) is a **Phase 3 spike**, decided
   immediately before authoring content, not now.
3. **`app.yaml` parameter structure:** **resolved** — confirmed against the upstream
   LinkML schema directly (commit `45f4359`). Top-level `parameters: map[string]Parameter`;
   constraints live under `configuration.schema`, linked via `configuration.sections[].settings[]`.
   See Item 4 for the join logic.
4. **`--remote` scope:** **resolved — descoped from Sprint 6 entirely.** Moved to
   `ROADMAP.md` backlog. Not implemented this sprint; no decision needed now on variants
   vs primary versions until it's picked back up.
5. **Descriptor location with templating:** **resolved** — `verify` renders
   `app.yaml.jinja` to a temp file and validates that; it never reads `<build_dir>` and
   never requires a prior `build`. See Item 3.
6. **Schema B pass/fail semantics:** **resolved** — lint by default (report only, exit 0),
   contract with `--strict` (any finding exits 1). The LinkML-severity → margot-severity
   mapping is finalized with the Phase 3 spike.
7. **Example/fixture descriptor:** **resolved — none shipped this sprint.** No golden
   `app.yaml` is added to `docs/examples/`; tests use minimal inline YAML. Users rely on
   the warnings and errors `verify` prints to work out what to fix.
8. **LinkML plugin viability** (`MaximumCardinalityPlugin` availability, `closed=True` vs
   `x-placeholder-extensions`): **resolved as tune-after-implementation** — wire all
   three, evaluate against real input, drop what misbehaves before release (Phase 4).
