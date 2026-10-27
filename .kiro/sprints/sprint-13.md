# Sprint 13 — `margot.yaml` project file and `margot migrate`

**Status:** design settled — awaiting Gate 1 (branch/worktree split)
**Type:** feature (Item 2 is a breaking rename with a compatibility window until 1.0.0)
**Owner:** python-dev (docs: docs-writer)
**Release:** planned for `release/X.Y.Z` (TBD, after Sprints 11 and 12); Item 1 may ship earlier as a patch

---

## 1. Goal

1. Rename the project descriptor from `margo.yaml` to **`margot.yaml`** (same content, still
   `apiVersion: v1`). The file is margot's own, not part of the Margo standard, so it must
   not look like a Margo-spec file or an anchor other tools should use. `margot migrate`
   performs the rename.
2. `margot migrate` also **adopts an existing Margo manifest** (typically after
   `margot pull --recursive`) by generating `margot.yaml` and the margot project layout
   around it, and with `--components` organises the pulled components into
   `compose/` / `quadlet/` variant folders.
3. Supporting changes this needs: a safe `pull --recursive` (Item 1) and a per-variant
   `repository` in `margot.yaml` (Item 3).

Target workflow:

```text
margot pull <uri> --recursive     # layer dump + component archives
margot migrate                    # in the current folder: margot.yaml + margo/ layout
margot migrate --components       # ... and organise the components too
```

---

## 2. Context

- Today `margo.yaml` anchors a project (`--project-dir`), is read by `build`, `push`,
  `package`, `verify`, `describe`, and feeds `app.yaml.jinja` as `manifest.*`.
- Sprint 12 makes `describe`/`verify` work on a bare `app.yaml` and defers adoption of such
  manifests to `migrate`. Its decision that `pull` stays a plain layer dump stands: `pull`'s
  output layout is not changed here.

Dependencies — land first, then branch from the release branch:

- **Sprint 11** — `mediaType`-based descriptor lookup; `resolve_margo_resource_files`
  driven by `app.yaml` fields (picks the files belonging to the margo artifact).
- **Sprint 12** — `resolve_descriptor` fallback (`<dir>/app.yaml`, then
  `<dir>/margo/app.yaml`). Item 2 updates that code and its tests to the new filename.
- Sprint 10 (exit codes / `--json`) is not a dependency; use `console.fatal` as it exists
  at implementation time.

Facts verified against source:

- Hard-coded `"margo.yaml"` path joins: 5 sites in `src/` (`services/build.py`, `push.py`,
  `package.py`, `verify.py` ×2). Plus ~259 occurrences in `*.py` (mostly tests and error
  strings) and ~163 in `*.md`.
- `VariantConfig` has **no per-variant `repository`**; all variants of a type share one
  (`docs/templating.md` already documents a per-variant override that the code lacks).
  Repository resolution happens per component type in `push.py`
  (`_resolve_registry_repository`) and `package.py` (`_resolve_component_repository`,
  `_add_component_to_bundle`, collision check), and in `domain/metadata.py`
  (`_build_component_context`).
- The project file has no helm concept; helm components live only in `app.yaml`.
- `validate_semver` normalises `_`→`+`, so a revision such as `1.0.9_compose-default` is a
  valid variant `version` verbatim and rebuilds to the identical tag.
- `pull --recursive` writes components to `<outdir>/<component-name>/<file>`; the file name
  is the layer title, else `<title>-<version>.tgz`, else a 12-char digest (no extension).
  Compose/quadlet archives are `.tgz` with one top-level `<name>/` directory.
- **Existing security bug:** `services/pull.py::_pull_recursive_components` builds
  `Path(outdir) / comp_ref.name` from the manifest's component name unsanitised; `../../x`
  or an absolute name escapes `outdir`, and manifests may come from an untrusted registry.
  `domain/layers.py::sanitize_filename` already exists for this.
- `package.py` already uses `tar.extractall(..., filter="data")` for untrusted archives.

---

## 3. Authoritative Design

Five items in one sprint, one branch each. Ordering: **Item 1 ∥ Item 2** → **Item 3 ∥
Item 4** → **Item 5** (Item 3 needs Item 2's filename; Item 4 needs Item 2; Item 5 needs 3
and 4). Items 1 and 2 are independently shippable.

### Item 1 — `fix(pull)`: sanitise component names in `--recursive`

Pass the component name through `sanitize_filename` before using it as a path; an unsafe
name (separators, `.`/`..`, NUL, empty) is skipped with a `console.warning` naming the
component, like other skipped components. Not a layout change. Regression tests with
`../x`, `a/b`, an absolute path, and a valid name (unchanged behaviour). Release first as a
patch so `pull -r` can be tried in the field before migrate lands.

### Item 2 — `margot.yaml` + legacy compatibility + `migrate` (rename mode)

**Canonical file:** `margot.yaml`. Internal names (`MargoYaml`, `load_margo_yaml`) are not
renamed; ROADMAP records the debt.

**One resolver, no scattered literals.** New `services/project.py::load_project(project_dir)
-> LoadedProject(meta, path, legacy)` used by all five call sites; constants
`PROJECT_FILE_NAME = "margot.yaml"` and `LEGACY_PROJECT_FILE_NAME = "margo.yaml"` in
`domain/metadata.py`.

| `margot.yaml` | `margo.yaml` | Result |
| --- | --- | --- |
| present | absent | load it |
| absent | present | load it **and** `console.warning` (once per invocation): legacy filename, run `margot migrate`, support **will be removed in 1.0.0** |
| present | present | error: ambiguous, remove one |
| absent | absent | error: `margot.yaml not found in <dir>. Create it manually, or run margot migrate to adopt an existing manifest.` (the old hint cites `margot init`, which does not exist) |

Sprint 12's no-project-file fallback keys on "neither file present". The legacy read path is
dropped at 1.0.0 (ROADMAP chore).

**`migrate` rename mode** (command introduced here; no URI/manifest handling yet):

- `margot migrate [--source-dir DIR] [--dry-run]`, `DIR` defaults to `.`.
- Only legacy file present → rename `margo.yaml` → `margot.yaml` in place (`Path.rename`,
  bytes unchanged — never parsed or rewritten; no git interaction); `console.success` with
  the new path, plus a warning that references in CI scripts/docs are not rewritten.
- `margot.yaml` present, legacy absent → `console.warning("nothing to do")`, exit 0
  (idempotent). Both present → `console.fatal`.
- Rename mode rejects `URI`, `--output`, `--components`, `--repository`, `--force`,
  `--all-repositories` (usage error naming the option).

**Sweep.** `src/` messages; all tests and fixtures to `margot.yaml` (keep explicit legacy
tests for the table); docs: `docs/margo-yaml.md` → `docs/margot-yaml.md` (+ `mkdocs.yml`,
all links; a redirect only if a redirects plugin is already configured), README,
`concepts.md`, `templating.md`, command pages, examples, `TESTING.md`,
`.kiro/steering/product.md`, `documentation.md`. Incidental: `oci-media-types.md` labels
`application/vnd.margo.app.description.v1+yaml` as the "`margo.yaml` descriptor"; it is the
`app.yaml` layer. The `margo/` source **directory** and `directory: margo` default are
unrelated and unchanged.

### Item 3 — per-variant `repository` in `margot.yaml`

Needed so `migrate --components --all-repositories` can represent components living in
different repositories.

- `VariantConfig.repository: str | None = None`; parsed from the variant mapping; if present
  it must be a non-empty string (`ValueError` like `image` validation otherwise).
- **Effective repository** = `variant.repository` → `component.repository` → top-level
  `repository` (then CLI/config exactly as today). Feed this effective value into the
  existing resolvers: CLI-vs-file precedence is **unchanged**.
- Template context: `variant.repository` and `variant.ref` use the effective repository
  (`manifest.<type>.repository` stays the component-level value). Matches what
  `docs/templating.md` already says.
- `push.py`: variant pushes resolve registry/repository from the effective repository.
- `package.py`: bundle layout and collision detection become per-variant (a bundle folder
  per effective repository; collision key `(repository, filename)`); verify image discovery
  is unaffected.
- No change when the field is absent.
- Docs: variant-fields table in `margot-yaml.md`; reconcile `templating.md`.
- Tests: parse/validation; context; push resolution (variant overrides component, absent
  inherits, CLI precedence unchanged); package bundle layout and collision with mixed
  repositories.

### Item 4 — `migrate`: adopt an existing manifest (margo artifact only)

```text
margot migrate [URI] [--source-dir DIR] [--output DIR] [--repository REPO]
               [--dry-run] [--force]
```

**Mode detection** (no mode flag):

| Situation | Mode |
| --- | --- |
| `URI` given | adopt, remote source |
| no `URI`; source dir has only `margo.yaml` | rename (Item 2) |
| no `URI`; no project file; descriptor found (Sprint 12 search order) | adopt, local source |
| `margot.yaml` present | nothing to do / ambiguous, as Item 2 |
| no `URI`, no project file, no descriptor | error listing the paths tried |

`--source-dir` and `--output` default to `.` (the folder you just pulled into). `URI` and
`--source-dir` are mutually exclusive.

**Layout produced** (`<output>`):

```tree
<output>/
├── margot.yaml
└── margo/
    ├── app.yaml           # verbatim, always static; named app.yaml whatever the source called it
    └── resources/...      # files chosen by Sprint 11 resolve_margo_resource_files
```

**In place vs copy.** Source dir == output dir → the margo files (`app.yaml` and the
resources `resolve_margo_resource_files` selects) are **moved** into the layout: no copy is
left behind. Different dirs, or a URI source → files are copied/pulled and the source is
never touched. If the descriptor is already at `<output>/margo/app.yaml` (Sprint 12
candidate 2) nothing is moved; only `margot.yaml` is written. Anything not carried over
(component archive folders without `--components`, stray files) stays untouched and is named
in one warning.

**`app.yaml` is never templated** (owner decision): parameters, configuration, helm
profiles, `requiredResources`, `catalog.application` and extensions cannot be meaningfully
templated, so the manifest is copied verbatim and nothing is dropped.

**Collisions.** Without `--force`, error if a target exists: `<output>/margot.yaml` or
legacy `margo.yaml` (use rename mode), a non-empty `<output>/margo/` (unless it is the
descriptor-already-laid-out case), and with `--components` the specific `<type>/<variant>/`
folders (never the whole `compose/` / `quadlet/`). `--force` replaces only those targets.

**Safety.** Plan everything first (parse, map, validate; Item 5: fetch + extract into a
staging dir inside `<output>`), then commit: move staged results into place, then — in place
only — remove the originals that were moved. A failure before commit leaves the folder as it
was. `--dry-run` runs the plan and prints the generated `margot.yaml`, warnings, and the
files that would be written/moved/removed; writes nothing.

**Mapping `app.yaml` → `margot.yaml`:**

| `margot.yaml` | Source | Rule |
| --- | --- | --- |
| `apiVersion` | — | constant `v1` (the project file's own schema version) |
| `id` | `id` | verbatim; missing → error |
| `name` | `metadata.name` | **verbatim** (owner decision; it is `manifest.name` in templating). Whitespace → warning that archive/bundle file names will contain spaces. If `sanitize_filename(name)` is `None` (path separators, `.`/`..`, NUL) or the name is empty → fall back to a slug (lowercase, non-`[a-z0-9]` runs → `-`), else `id`, with a warning — `name` is used in `<name>-<version>.tgz` paths |
| `version` | `metadata.version` | verbatim **string**; a YAML-coerced non-string (e.g. `1.0` → float) is `str()`-ed with a warning; non-SemVer → warn that `build`/`push` will reject it until fixed |
| `description` | `metadata.description` | missing → `metadata.name` + warning (field required) |
| `repository` | `URI` repository part (tag stripped) or `--repository` | `--repository` wins; local source with neither → omit + warning; URI tag ≠ `metadata.version` → warning |
| `author`, `organization` | `metadata.catalog.author` / `.organization` | verbatim lists |
| `appVersion`, `annotations`, `directory` | — | omitted (no manifest equivalent / default) |

**Contracts / layering** (TDD; tests before code):

- `domain/uri.py`: `extract_repository(uri)` (pure).
- `domain/metadata.py`: `margo_yaml_to_dict(meta)` — stable key order (`apiVersion, id,
  name, version, appVersion, description, directory, repository, author, organization,
  annotations, compose, quadlet`; variants: `name, version, component, repository, image`),
  omitting `None`/empty/default values.
- `domain/migrate.py` (new, pure; no I/O, `console`, `rich`): `plan_migration(app_doc, *,
  source_uri, repository_override, include_components, all_repositories) ->
  MigrationPlan` (a `MargoYaml`, planned components, warning strings); name/slug/
  directory-safe helpers.
- `infra/filesystem.py`: `write_yaml`, move/copy helpers, staging-dir commit (all
  `console.debug`).
- `services/migrate.py` (new): orchestration. Remote: `resolve_remote_descriptor` (temp dir
  cleaned in `finally`); local: Sprint 12 resolution. `console.info` per step.
- `commands/migrate.py`: Typer parsing, mode and mutual-exclusion checks, warnings,
  `console.success` per written path; register in `main.py`; README command table.
  Manifest values displayed per `rich-rendering.md` (no markup interpolation).

### Item 5 — `migrate --components` (its own feature)

Default `migrate` produces only the margo artifact (no `compose`/`quadlet` blocks), so the
project builds and pushes as-is and the component references in `app.yaml` keep pointing at
the already-published artifacts. `--components` additionally declares and organises
components:

1. **Eligibility** — profile `type` is `compose` or `quadlet`, component has
   `properties.repository` and `properties.revision` (`oci://` stripped). Anything else
   (helm, unknown types, incomplete properties) is skipped with a named warning ("no
   `margot.yaml` equivalent; remains referenced in app.yaml").
2. **1:1 variant per component**, under the type block: `name` = component name made
   directory-safe (`[A-Za-z0-9._-]`, other characters → `-`; collision with
   `_RESERVED_VARIANT_NAMES` appends `-variant`); `component` = original name, **always
   written explicitly** (parameter targets in `app.yaml` reference component names);
   `version` = `revision` verbatim.
3. **Repositories.**
   - *Default:* per type, the first eligible component's repository (manifest order) is the
     one repository handled; it becomes `<type>.repository` (omitted if equal to the
     top-level `repository`). Components of that type in any other repository are skipped
     with a warning naming each and suggesting `--all-repositories`.
   - *`--all-repositories`:* no restriction. Every eligible component is organised. The
     type block keeps the first component's repository; each variant whose repository
     differs gets an explicit `repository` (Item 3). Requires `--components` (usage error
     otherwise).
4. **Dedup** — identical `(type, name, repository, revision)` across profiles → one variant;
   same name with a different repository/revision → keep first, warn (variant folders must
   be unique, even with `--all-repositories`).
5. **Buildability invariant** — a revision failing `validate_oci_tag`/`validate_semver` is
   skipped with a warning. Every variant written to `margot.yaml` must build.
6. **Source of the archive (local first)** — if the source dir holds `<component-name>/`
   (written by `pull --recursive`) with exactly one regular file that is a tar archive, use
   it (offline). Otherwise, or if ambiguous, fetch `<repository>:<revision>` via
   `prepare_oci_retrieval` (credentials per registry host); the detected `PackageType` must
   match the profile type, else skip + warn. The component name used as a local path goes
   through `sanitize_filename`; unsafe → skip + warn.
7. **Safe extraction** — `tarfile` with `filter="data"` into the staging dir, stripping the
   single top-level directory, destination `<output>/<type>/<variant>/`. Hostile archives
   (absolute paths, `..`, escaping symlinks) fail that component and never write outside
   staging.
8. **Fail-soft per component** — any fetch/extract failure drops only that variant from
   `margot.yaml` (never declare a variant without sources), with a warning.
9. **In-place cleanup (no copy left behind)** — after commit, an extracted component's
   `<component-name>/` folder is removed if it contained nothing but the consumed archive;
   if it holds anything else it is left in place and named in the warning. Not in place:
   source untouched.
10. Resulting block: `directory` and `version` omitted, `variants` as above, no `image`
    block (pulled content is already final).

Rebuilt component archives are semantically equal to the originals, not digest-identical.

### Non-goals (explicit)

- No `app.yaml.jinja` generation (ROADMAP: at most partial templating of managed fields,
  later, low priority).
- No helm support; no `margot init`; no `appVersion`/`annotations` flags.
- No rename of Python identifiers (`MargoYaml`, `load_margo_yaml`).
- No change to `pull`'s output layout; `pull -r` stays a staging step and `migrate
  --components` is the organiser.
- No removal of legacy `margo.yaml` reading in this sprint (dropped at 1.0.0).
- No digest-reproducibility guarantee for rebuilt components.

---

## 4. Checkable Steps

TDD throughout. Each task is one or more conventional commits on its item's branch.

### Item 1 — pull fix

- [ ] Tests first: unsafe/absolute/valid component names in `pull --recursive`.
- [ ] Implement sanitisation + warning in `_pull_recursive_components`.
- [ ] `docs/commands/pull.md`: note skipped unsafe names.

### Item 2 — rename

- [ ] Tests first: `load_project` table (all four rows), warning once and mentions 1.0.0;
  rename mode (byte-identical, idempotent, both-present error, rejected options, `--dry-run`).
- [ ] Implement constants, `services/project.py`, switch the 5 call sites, update messages.
- [ ] Implement `commands/migrate.py` rename mode; register in `main.py`.
- [ ] Sweep tests/fixtures to `margot.yaml` (keep explicit legacy tests).
- [ ] Update Sprint 12 code/tests to the new filename (if merged).
- [ ] Docs sweep (docs-writer) incl. `docs/margot-yaml.md`, nav, links, new
  `docs/commands/migrate.md` (rename mode), deprecation note. `make docs-check` passes.
- [ ] `grep -rn "margo\.yaml"` leaves only intentional legacy references.

### Item 3 — per-variant repository

- [ ] Tests first (see §3 Item 3 list).
- [ ] Implement `metadata.py` (parse, context), `push.py`, `package.py` changes.
- [ ] Docs: `margot-yaml.md`, `templating.md`. `make docs-check` passes.

### Item 4 — adoption

- [ ] Tests first: `extract_repository`; `margo_yaml_to_dict` (order, omissions, loads back);
  `plan_migration` over `complex.yaml`, `minimal.yaml`, `missing-required.yaml` and new
  fixtures (float version, missing description, name with spaces / separators / empty).
- [ ] Implement domain, infra helpers, `services/migrate.py` (local, remote, in-place move,
  copy, already-laid-out case, staging/commit, `--force`, `--dry-run`).
- [ ] Integration: pulled dir in place (no leftovers), `--output` elsewhere (source
  untouched), remote URI via the Sprint 9 fakes, every error row, failure before commit
  leaves the folder unchanged.
- [ ] Round trip: `load_project` works; `verify` verdict equals verifying the source
  `app.yaml`; `build -t margo` yields an `app.yaml` byte-identical to the source.
- [ ] Docs: adoption section, mapping table, `pull -r` → `migrate` workflow.

### Item 5 — components

- [ ] Tests first: planning rules 1–5 (incl. default one-repository vs `--all-repositories`,
  `--all-repositories` without `--components`); local-archive discovery (0/1/many files,
  non-tar); registry fallback with type mismatch; unsafe name; hostile-archive extraction;
  fail-soft drop; in-place cleanup rules.
- [ ] Implement planning, extraction helper, service flow, both flags.
- [ ] Integration (faked registry + `pull -r`-shaped dir): compose + quadlet + helm manifest
  across two repositories → default skips and warns; `--all-repositories` organises all,
  variants carry `repository`; helm warned.
- [ ] Round trip: `build -t all` succeeds and each built component's
  `version.replace("+","_")` equals its `revision` in `app.yaml`; `push --dry-run` resolves
  each variant's own repository.
- [ ] Docs: `--components`, `--all-repositories`, helm note.

---

## 5. Definition of Done

- [ ] All checkable steps completed.
- [ ] `make check` passes (lint + unit + integration, coverage threshold).
- [ ] E2E: `pull --recursive` (faked registry) → `migrate --components` → `verify`,
  `describe`, `build -t all` run cleanly in the same folder.
- [ ] Docs updated; `make docs-check` passes.
- [ ] No bare TODOs (`# TODO(kiro): ...` with a ROADMAP entry only).
- [ ] Close-out: ROADMAP Completed table; backlog trimmed (per-variant repository and pull
  fix done; keep legacy-removal-at-1.0.0 chore and identifier rename); `product.md` command
  list; sprint file deleted in `chore(sprint): close out sprint-13 — margot.yaml and migrate`.
- [ ] Each task committed on its branch — no bulk commit.
- [ ] Handed back for review (Gate 2); the agent does not push, open PRs, or manage worktrees.

---

## 6. Close-out Note

```
(filled in after merge)
```

---

## 7. Decisions (all settled by owner)

1. `app.yaml` stays static.
2. Default is in place in the current folder; `--output` selects another folder.
3. `--components` is its own item in this sprint.
4. Project file becomes `margot.yaml`, same content, renamed by `migrate`; legacy
   `margo.yaml` read with a deprecation warning and dropped at 1.0.0.
5. No copy left behind when migrating in place.
6. `pull --recursive` sanitisation fix is included, first.
7. One sprint.
8. `name` = `metadata.name` verbatim (safe fallback only when unusable as a file name).
9. Components: one repository per type by default; `--all-repositories` lifts the limit,
   which requires per-variant `repository` (Item 3).

---

## References

- [sprint-workflow skill](../skills/sprint-workflow/SKILL.md)
- [ROADMAP.md](../../ROADMAP.md)
- [sprint-11.md](./sprint-11.md), [sprint-12.md](./sprint-12.md) — prerequisites.
- Steering: `code-conventions.md`, `rich-rendering.md`, `oci-media-types.md`,
  `documentation.md`.
