# Sprint 5 — Jinja2 build refactor + auth polish

**Goal:** Ship the Jinja2 `app.yaml` rendering pipeline (Theme C — breaking refactor),
`margot auth status`, and authenticated `fetch`/`pull`. All three are self-contained
enough to land in the same sprint; Theme C is the heavyweight item.

---

## Scope

### Item 1 — `margot auth status`

Read-only command. No network calls, no mutations.

**CLI:** `margot auth status`

**Behaviour:**
- Read `~/.config/margot/credentials.toml` (via `infra/credentials.py`).
- Read oras-py credential store to detect registries that have credentials but no
  margot expiry entry.
- For each registry tracked in the margot file: display hostname, `expires_at`,
  time remaining, and a status label (VALID / EXPIRING / EXPIRED).
  - VALID: more than 5 min remaining.
  - EXPIRING: ≤ 5 min remaining (mirrors the warning threshold in `check_credentials`).
  - EXPIRED: `now >= expires_at`.
- For each registry present only in the oras-py store: display hostname + "present but
  expiry unknown".
- If neither file has any entries: print a clear message ("No credentials tracked.") —
  never an empty table.

**Output:** rich table (hostname | expires_at | remaining | status).

**Files touched:**
- `src/margot/infra/credentials.py` — add `list_tracked()` → `list[tuple[str, datetime]]`,
  and `list_oras_registries()` → `list[str]` (reads oras-py Docker config).
- `src/margot/services/auth.py` — add `auth_status()` → structured result type.
- `src/margot/commands/auth.py` — add `status` subcommand, render the table.
- `tests/unit/test_credentials.py` — extend with `list_tracked` / `list_oras_registries`.
- `tests/integration/test_auth_service.py` — `auth_status()` with various file states.
- `tests/e2e/test_auth_cli.py` — `status` subcommand: no creds, tracked, expiring, expired.

---

### Item 2 — Authenticated `fetch` and `pull`

Wire the existing `check_credentials` guard and oras-py auth into the two anonymous-only
services.

**Current state:** `services/fetch.py` and `services/pull.py` create `OrasClient()`
with no auth. The `check_credentials` guard only runs before push.

**Changes:**

`infra/oci.py`:
- Add `OrasClient(hostname: str | None = None)` optional parameter. When `hostname` is
  supplied, call `self.auth.load_configs(self.get_container(...))` on construction so
  stored credentials (if any) are loaded automatically.

`services/fetch.py` — `fetch_manifest(uri)`:
- Parse hostname from URI (reuse `domain/uri.py`).
- Call `check_credentials(hostname)` before creating the client.
- Pass `hostname` to `OrasClient(hostname)`.

`services/pull.py` — `pull_artifact(uri, ...)`:
- Same pattern: parse hostname, `check_credentials`, pass to `OrasClient`.

No new CLI flags needed. Auth is transparent: if credentials exist in the oras-py
store they are used; if not, the request proceeds anonymously (same as today).

**Files touched:**
- `src/margot/infra/oci.py` — optional hostname param on `__init__`.
- `src/margot/services/fetch.py` — add credential check + hostname threading.
- `src/margot/services/pull.py` — same.
- `tests/unit/test_infra_oci.py` — OrasClient with hostname.
- `tests/integration/test_fetch_service.py` — expired creds → error; valid creds → pass-through.
- `tests/integration/test_pull_service.py` — same.

---

### Item 3 — Breaking refactor: `app.yaml` Jinja2 rendering

This is the breaking change. Ships as a single commit (or two: non-breaking Jinja2 path
first, then remove old placeholders — your call at implementation time).

#### 3a. New `id` field in `margo.yaml`

`id` becomes a required top-level field. It is the stable machine identifier for the
application, used as a base for derived component name defaults in the Jinja2 context.

- `domain/metadata.py` — add `id: str` to `MargoYaml`; make it required (raise
  `ValueError` if absent).
- All existing test fixtures in `tests/` that construct or parse `margo.yaml` must be
  updated to include `id`.

#### 3b. Jinja2 `app.yaml.jinja` rendering in `services/build.py`

File resolution rules (in `_build_margo`):
1. Both `app.yaml.jinja` and `app.yaml` present in source → **hard error** (fail build,
   clear message).
2. `app.yaml.jinja` present → render with Jinja2 `StrictUndefined`, write output as
   `app.yaml` in the build dir. The `.jinja` source must NOT be copied to the output.
3. `app.yaml.jinja` absent → copy `app.yaml` verbatim. No substitution.

Jinja2 template context (derived read-only from `MargoYaml`):

```
manifest.id
manifest.name
manifest.version
manifest.appVersion          (empty string if absent)
manifest.description
manifest.annotations         (dict)
manifest.author              (list)
manifest.organization        (list)

manifest.margo.version
manifest.margo.tag           (version with '+' replaced by '_')
manifest.margo.ref           (repository:tag)
manifest.margo.repository
manifest.margo.directory

manifest.compose.directory
manifest.compose.repository
manifest.compose.variants    (ordered list of variant objects, see below)
manifest.compose.<name>      (direct access by variant name — e.g. manifest.compose.minimal.tag)

manifest.quadlet.*           (same shape as compose)
```

Variant object fields: `name`, `version`, `tag` (OCI-safe), `ref` (`repository:tag`),
`repository`, `component`.

- `tag` = `version` with `+` → `_`.
- `ref` = `{repository}:{tag}`.
- `component`: developer-owned. Default = `{id}-{type}-{name}` (e.g. `myapp-compose-minimal`).
  Never overwritten if explicitly set in `margo.yaml`.
- Flat components (no `variants` declared) expose a single synthetic entry in `variants`
  so templates can iterate uniformly.
- Variant names that collide with reserved field names (`directory`, `repository`,
  `variants`, `version`, `tag`, `ref`, `component`) must be rejected at `metadata.py`
  parse time with a clear `ValueError`.

**New dependency:** `jinja2` — add to `pyproject.toml` dependencies.

#### 3c. Remove old placeholder substitution from the margo build path

- Remove `<app_tag>`, `<margo_tag>`, `<compose_tag>`, `<quadlet_tag>`,
  `<helm_chart_tag>` from the placeholder map that feeds `app.yaml`.
- These placeholders **remain** for compose/quadlet text files (plain string replace
  stays the right model there).
- `_build_placeholder_map` is retained for compose/quadlet but no longer used for margo.
- Update `services/build.py` `_build_margo` accordingly.

#### 3d. Placeholder coverage and error handling for compose/quadlet

- Formally enumerate all supported placeholders in a constant or docstring in
  `infra/filesystem.py` `substitute_placeholders`.
- Add a warning (via `console.warning`) when a text file in the source tree contains
  a `<..._tag>` pattern that is not in the placeholder map (unresolved placeholder).
  Do not hard-fail — warn and continue.

**Design (locked, confirmed with project owner) — `image` search/replace block:**

**Problem re-framed:** the old placeholder model (`<compose_tag>` etc. substituted
directly into compose/quadlet source files) is wrong for this case — it means the
checked-in `compose.yaml`/`.container` file is not a real, runnable file; it's a template
the developer can't `podman compose up` locally as-is. The goal is the opposite: the
component source is a **usable, runnable artifact as checked in** (developer runs it
locally against a real dev image), and `margot build` does a **targeted string
replacement of that one known dev image reference** with the environment-appropriate
ref (dev/qa/prod), rather than filling in a blank. The old `<..._tag>` placeholders
for compose/quadlet **image references** are dropped — they never made sense for this
purpose. (The `<..._tag>` placeholders for `app.yaml` are unaffected — `app.yaml` is
only ever rendered once at build/publish time, never run directly, so template
placeholders there are fine and out of scope for this change.)

**Shape — new optional `image` block per component and per-variant, in `margo.yaml`:**

```yaml
compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
  image:
    search: "myapp:dev"                                          # exact literal string as it appears in the source file(s)
    replace: "public.ecr.aws/g2n4p2m7/myapp:<app_tag>"            # target ref; may reuse existing placeholder syntax
  variants:
    - name: default
      version: 1.0.0
      # inherits the component-level `image` block above (no override)
    - name: gpu
      version: 1.0.0_gpu
      image:                                                      # per-variant override — replaces, not merges
        search: "myapp:dev-gpu"
        replace: "public.ecr.aws/g2n4p2m7/myapp:<app_tag>-gpu"
```

```yaml
quadlet:
  directory: quadlet
  version: 1.0.0
  image:
    search: "myapp:dev"
    replace: "public.ecr.aws/g2n4p2m7/myapp:<app_tag>"
```

**Rules:**

1. **One `search`/`replace` pair per component (or per-variant override).** Multi-image
   support (project owner's decision) is achieved by declaring multiple components or
   variants — each with its own `image` block — not by a list of image mappings within
   one block. Keeps the mechanism format-agnostic: it's a literal string replace on text
   files, same primitive already used for placeholder substitution, no YAML-key-aware
   parsing of `image:` lines (which would require compose- and quadlet-specific parsers).
2. **`search` is a literal string**, not a regex. Matched and replaced across all text
   files in the component's source dir (respecting `.rsyncignore`, same as existing
   substitution).
3. **`replace` may reuse existing placeholder tokens** (e.g. `<app_tag>`) — resolved the
   same way and at the same time as other compose/quadlet placeholders. No Jinja here;
   Jinja is reserved for `app.yaml.jinja` (Item 3b) only.
4. **Variant-level `image` fully overrides** the component-level one (replace semantics,
   not merge) — needed because variants can legitimately point at entirely different
   local dev images (e.g. a `gpu` variant).
5. **Optional.** If a component/variant declares no `image` block, no image substitution
   runs for it — same posture as other unresolved-placeholder handling (warn, don't
   fail). Not every component necessarily has a dev-local image reference to swap.
6. **Unmatched `search` string** (declared but not found in any source file) — warn via
   `console.warning`, do not hard-fail. Mirrors the unresolved-placeholder warning in 3d.

**`domain/metadata.py` changes:**
- New `ImageConfig` dataclass: `search: str`, `replace: str`.
- `ComponentConfig` gains `image: ImageConfig | None`.
- `VariantConfig` gains `image: ImageConfig | None` (override, not merged, when present).
- Parse `image` block under both component root and each variant entry; validate both
  `search` and `replace` are present and non-empty when an `image` block exists.

**`infra/filesystem.py` / `services/build.py` changes:**
- Image search/replace runs as part of the same text-substitution pass as placeholder
  substitution for compose/quadlet (not a separate walk).
- Resolve effective `image` config per variant: variant's own `image` if present,
  else the component-level `image`, else none.

**Files touched (additive to the list below):**
- `src/margot/domain/metadata.py` — `ImageConfig`, `ComponentConfig.image`,
  `VariantConfig.image`, parsing + validation.
- `src/margot/infra/filesystem.py` — extend substitution pass to include image
  search/replace; unmatched-search warning.
- `src/margot/services/build.py` — resolve effective `image` config per variant/component
  and pass it into the substitution call for compose/quadlet builds.
- `tests/unit/test_metadata.py` — `ImageConfig` parsing, variant override, missing
  fields.
- `tests/unit/test_filesystem.py` — search/replace applied, unmatched search warns.
- `tests/integration/test_build.py` — end-to-end: component-level image sub, variant
  override, no `image` block declared (no-op).
- **`FEATURES.md` update required** — add `image` block to the `margo.yaml` format
  reference (compose/quadlet sections) and to the Package Types section. This is new
  spec surface, not implementation detail — must land in `FEATURES.md` per
  `documentation.md` steering rules (spec first, docs follow).

**Files touched:**
- `pyproject.toml` — add `jinja2` dependency.
- `src/margot/domain/metadata.py` — add `id` field; add variant name collision check;
  add `component` field to `VariantConfig`; build Jinja2 context helper.
- `src/margot/services/build.py` — new `_build_margo` Jinja2 path; remove old placeholder
  substitution from margo path.
- `src/margot/infra/filesystem.py` — add unresolved placeholder warning.
- All test fixtures using `MargoYaml` or `margo.yaml` YAML content — add `id` field.
- `tests/unit/test_metadata.py` — new cases: `id` missing, variant name collision,
  Jinja2 context shape.
- `tests/integration/test_build.py` — new cases: `.jinja` present, both present (error),
  static copy, unresolved placeholder warning.
- `tests/e2e/test_build_cli.py` — smoke tests for Jinja2 and verbatim paths.

---

## Definition of done

- [ ] All three items implemented.
- [ ] `uv run pytest` passes with no failures.
- [ ] No `# TODO` markers left from this sprint's work.
- [ ] All new code follows `code-conventions.md` (console output, imports, TODO format).
- [ ] `ROADMAP.md` updated: Sprint 5 items moved to Completed Sprints table; backlog
  entries struck or removed.
- [ ] Commit: `feat(sprint-5): auth status, authenticated fetch/pull, Jinja2 app.yaml rendering`
  (or split into logical commits matching the three items).

---

## Open questions / decisions locked

- **Breaking change strategy:** Jinja2 path and placeholder removal ship in the same
  sprint. No deprecation window (margot is pre-1.0, unpublished).
- **`component` field:** developer-owned, margot computes a default but never overwrites
  an explicit value. Stored in `VariantConfig` and surfaced in the template context.
- **Flat components in Jinja2 context:** always exposed as a single synthetic variant
  entry in `variants` so templates iterate uniformly regardless of layout.
