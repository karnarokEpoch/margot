# Sprint 6 — `margot verify`

**Goal:** Ship a complete `margot verify` command: local-only LinkML validation against
the upstream Margo spec schema (always-on) and an opt-in (`--recommend`) margot-curated
recommended schema, plus an opt-in (`--deep`) structured rich display of the full
`app.yaml` state. Default output (no flags) is plain CI-check-style pass/fail. Remote
artifact reachability checking is descoped to the backlog (see `ROADMAP.md`).

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
(exit 1). Schema B failures are warnings (exit 0 unless `--strict`). The output labels
each finding clearly with its source schema.

---

## Build phases

The five scope items below are implemented in **four sequential phases**, not as one
batch. Each phase should be its own PR/commit and should leave `verify` in a working
state — this lets Schema A ship and be useful before Schema B content exists.

**Phase 1 — Schema A only, minimal command.**
Vendor Schema A (Item 2, Schema A part only), build `validation/linkml_runner.py` +
`error_formatter.py` (Item 1), and wire a minimal `margot verify` that runs Schema A
only and prints plain pass/fail (Item 3 + a minimal slice of Item 5 — no `--recommend`,
no `--deep` yet). Definition of "done" for this phase: `margot verify` correctly
validates `app.yaml` against the real upstream schema end to end.

**Phase 2 — Display layer.**
Add `--deep` structured display (Item 4 in full) and finish CLI flag wiring for
everything except `--recommend`/Schema B (rest of Item 5). `verify` now has its full
default-vs-`--deep` behavior, still Schema A only.

**Phase 3 — Schema B authoring + integration.**
Author `margo-recommended.linkml.yaml` content (remainder of Item 2) and wire
`--recommend` into `services/verify.py` and the command output (remainder of Item 3 and
Item 5) — including the A/B section separator requirement.

**Phase 4 — Polish and DoD closure.**
`--strict` behavior, edge cases (Schema A clean + `--recommend` clean → no stray B
section), full e2e test pass, `ROADMAP.md` update, final commit.

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
  `ValidationFinding(field_path, message, severity)` dataclass so `commands/verify.py`
  and `error_formatter.py` never import `linkml` types directly (see layer rule in
  `AGENTS.md`). No per-field special-casing beyond what LinkML already reports.
- `src/margot/validation/error_formatter.py` — format a validation result into a
  `rich.table.Table` row or a plain string. Extracts field path, message, severity.
- `src/margot/validation/max_cardinality.py` — `MaximumCardinalityPlugin` implementation
  (if not provided by the installed linkml version; otherwise a thin re-export).

**Dependency:** `linkml` — add to `pyproject.toml`.

**Tests:**
- `tests/unit/validation/test_linkml_runner.py` — run against a minimal fixture schema
  and a known-good / known-bad YAML. Covers: all-pass, single error, warning-only.
- `tests/unit/validation/test_error_formatter.py` — format a mock result; check table
  output shape, severity labels.

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
for validation against a final/stable spec. Surface this via `console.info` in
`commands/verify.py`, not buried in `--debug` output.

**Schema B (recommended):** lives in `src/margot/schemas/margo-recommended.linkml.yaml`.
Content TBD in implementation, but must at minimum cover:
- `org.opencontainers.image.title` annotation present.
- `description` non-empty string.
- At least one `component` entry.
- Recommended resource files (icon, release-notes, description file) flagged as
  `RecommendedSlots`.

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
    manifest_path: str = "margo/app.yaml",
    schema_path: str | None = None,              # override Schema A
    recommended_schema_path: str | None = None,   # override Schema B
    recommend: bool = False,                      # enable Schema B (see Item 5)
    strict: bool = False,                         # treat Schema B warnings as errors
) -> VerifyResult
```

`VerifyResult` dataclass (in `domain/` or inline):
```
schema_a_results: list[ValidationFinding]
schema_b_results: list[ValidationFinding]   # empty when recommend=False
passed: bool
```

`ValidationFinding`: `field_path`, `message`, `severity` (ERROR / WARNING / INFO).

**Local validation flow:**
1. Load `app.yaml` (path from CLI or default).
2. Run Schema A validation → `schema_a_results`. Any ERROR → `passed = False`.
3. If `recommend=True`, run Schema B validation → `schema_b_results`. Any ERROR (or
   WARNING if `--strict`) → `passed = False`. If `recommend=False`, `schema_b_results`
   stays empty and Schema B is not run at all.

**Files:**
- `src/margot/services/verify.py`
- `tests/integration/test_verify.py` — good, bad (A), bad (B) with `recommend=True`,
  strict mode.

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

When `--deep` is passed and `app.yaml` passes structural validation, display a structured
summary of the file's content to support visual review. This is a rich rendering of the
parsed artifact, not a second validation pass.

**What to display (only with `--deep`):**

```
┌─ Application ──────────────────────────────────────────┐
│ id          myapp                                       │
│ name        My Application                             │
│ version     1.0.0                                      │
│ description Human-readable description                 │
└─────────────────────────────────────────────────────────┘

┌─ Components ───────────────────────────────────────────┐
│ type     tag       repository                          │
│ margo    1.0.0     public.ecr.aws/g2n4p2m7/margo      │
│ compose  1.0.0     public.ecr.aws/g2n4p2m7/margo      │
│ quadlet  1.0.0     …                                   │
└─────────────────────────────────────────────────────────┘

┌─ Parameters ───────────────────────────────────────────┐
│ name           type     required  default    range     │
│ image.tag      string   yes       2.3.1      —         │
│ replicas       integer  no        1          1..10     │
│ debug.enabled  boolean  no        false      —         │
└─────────────────────────────────────────────────────────┘
```

The parameters table is parsed from the top-level `parameters` map in the loaded
`app.yaml` (confirmed against the upstream schema: `ApplicationDescription.parameters`
is a `map[string]Parameter`, NOT nested under `deploymentProfile` — the open question
in this doc about the exact path is resolved). Each `Parameter` has `name`, `value`
(the default), and `targets`. Validation constraints (range, enum, regex) are NOT
inline on `Parameter` — they live separately under `Configuration.schema` (a list of
`Schema`/subclass objects keyed by `name`) and are linked back to a parameter only
indirectly via `Configuration.sections[].settings[].schema`. The parameters panel should
join `parameters` with `configuration.schema` via `configuration.sections[].settings[]`
(`setting.parameter` → param name, `setting.schema` → schema name) to show constraints;
if no matching `Setting`/`Schema` exists for a parameter, show default value only with
`—` for constraints.

**Implementation note:** parsing `app.yaml` for the display is separate from LinkML
validation. Use `pyyaml` directly — no linkml needed for this path. Only runs when
`--deep` is passed.

**Files:**
- `src/margot/commands/verify.py` — renders panels only when `--deep` is set, after
  `services/verify.py` returns. Without `--deep`, prints plain pass/fail lines via
  `console.success` / `console.fatal`. Parameters panel only shown if `app.yaml` loaded
  successfully (not if Schema A hard-fails with a parse error).
- No new service method needed — the command reads the manifest directly for display.

---

### Item 5 — `commands/verify.py` and CLI wiring

```
margot verify [--manifest PATH]
              [--schema PATH]
              [--recommended-schema PATH]
              [--recommend]
              [--strict]
              [--deep]
```

`--remote`, `--version`, `--registry`, `--repository` are removed from this sprint's
scope (see Item 3 decision) — tracked in `ROADMAP.md` backlog instead.

Defaults:
- `--manifest` → `margo/app.yaml` (same default as `FEATURES.md`).
- `--schema` → vendored Schema A path.
- `--recommended-schema` → vendored Schema B path.
- `--recommend` → off. Schema A always runs; Schema B does not run at all unless
  `--recommend` is passed (locked decision for Item 5 — see Background section note
  below).
- `--deep` → off. Plain CI-check-style pass/fail output by default (Item 4).

**Decision (locked) — Schema B default behavior:** Schema B is opt-in via `--recommend`,
not always-on-but-silent. When Schema A is run alone (default) and it produces no
findings, there must be no Schema B noise. When `--recommend` is passed and both schemas
produce findings, output must clearly separate them with a labeled section per schema
(e.g. a header/divider `── Schema A (Margo spec) ──` / `── Schema B (recommended) ──`)
so a reader never has to guess which schema a finding came from.

Output structure (always shown in this order):
1. Schema A results (errors only if all pass; full findings if any fail). Plain lines by
   default, table if `--deep`.
2. Schema B results — only shown at all if `--recommend` was passed. When shown, always
   under its own clearly labeled section, separated from Schema A's section.
3. Parameters / application summary panel — only if `--deep` and manifest loaded
   successfully.
4. Final pass/fail line.

Exit codes: 0 = passed, 1 = any error.

**Files:**
- `src/margot/commands/verify.py`
- `src/margot/main.py` — register `verify` command.
- `tests/e2e/test_verify_cli.py` — CLI smoke tests: missing manifest, valid, invalid
  (Schema A), `--recommend` warnings (Schema B), `--recommend` + `--strict`, `--deep`
  display, default (no flags) plain output, Schema A clean + `--recommend` clean (no
  stray B section).

---

## Definition of done

- [ ] All five items implemented (Item 3 local-only, no `--remote`).
- [ ] `uv run pytest` passes with no failures.
- [ ] Vendored schema file present, schema version constants declared, and draft-spec
      commit/version is surfaced in `verify` output.
- [ ] `margo-recommended.linkml.yaml` has at minimum the fields listed in Item 2, and only
      runs when `--recommend` is passed.
- [ ] Default (no flags) output is plain pass/fail, no panels, no tables.
- [ ] `--deep` renders the Application / Components / Parameters panels correctly for a
      manifest with at least two parameter types.
- [ ] `--recommend` output clearly separates Schema A and Schema B findings under
      distinct labeled sections.
- [ ] No `# TODO` markers left from this sprint's work.
- [ ] `ROADMAP.md` updated: Sprint 6 items moved to Completed Sprints table; `--remote`
      check added to backlog (Remaining commands section).
- [ ] Commit: `feat(sprint-6): verify command — LinkML validation, param inspection`

---

## Open questions to resolve at sprint start

All four resolved:

1. **Schema A vendoring vs download-on-demand:** ~~confirm before starting Item 2~~ —
   **resolved: vendored (option a)**, plus draft-spec version messaging (see Item 2).
2. **`margo-recommended.linkml.yaml` content:** plan above lists the minimum set; still
   walk through a real `app.yaml` from a known project during implementation to identify
   additional recommended fields, but the schema only runs when `--recommend` is passed
   (see Item 5).
3. **`app.yaml` parameter structure:** **resolved** — confirmed against the upstream
   LinkML schema directly (commit `45f4359`). Top-level `parameters: map[string]Parameter`;
   constraints live under `configuration.schema`, linked via `configuration.sections[].settings[]`.
   See Item 4 for the join logic.
4. **`--remote` scope:** **resolved — descoped from Sprint 6 entirely.** Moved to
   `ROADMAP.md` backlog. Not implemented this sprint; no decision needed now on variants
   vs primary versions until it's picked back up.
