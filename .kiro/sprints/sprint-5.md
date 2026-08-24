# Sprint 5 — Jinja2 build refactor + auth polish

**Goal:** Ship the Jinja2 `app.yaml` rendering pipeline (Theme C — breaking refactor),
`margot auth status`, and authenticated `fetch`/`pull`. All three are self-contained
enough to land in the same sprint; Theme C is the heavyweight item.

---

## Scope

### Item 1 — `margot auth status` ✓ done

Read-only command. No network calls, no mutations.

**CLI:** `margot auth status`

**Behaviour:**
- Read `~/.config/margot/credentials.toml` (via `infra/credentials.py`).
- Read oras-py credential store to detect registries that have credentials but no
  margot expiry entry.
- For each registry tracked in the margot file: display hostname, `expires_at`,
  time remaining, and a status label (VALID / EXPIRING / EXPIRED).
  - VALID: more than 1 hour remaining.
  - EXPIRING: ≤ 1 hour remaining (mirrors the warning threshold in `check_credentials`).
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

### Item 2 — Authenticated `fetch` and `pull` — ✅ DONE

> Implemented on `feat/update-fetch-pull`, commit `2e5074a`
> (`feat(auth): authenticate fetch and pull via stored OCI credentials`).
> `domain/uri.extract_hostname`, `infra/oci.OrasClient(hostname=...)`, and the
> `check_credentials` wiring in `services/fetch.py` / `services/pull.py` are all in
> place, with unit/integration/e2e coverage. No CLI flags were added — auth stays
> transparent. Do not re-implement; extend in place if requirements change.

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

### Item 3 — Breaking refactor: `app.yaml` Jinja2 rendering — ✅ DONE

> Implemented on `feat/jinja-rendering`, commits `249ea30`, `763b660`, `3001a94`,
> `d969ef0`, `11d3b11`. The design evolved during implementation — see
> **What actually shipped** below, which supersedes the original plan in this section
> where they differ (notably: no `margo:` block, top-level `version`/`directory` for
> the margo artifact, and optional variant `version` with derivation). Do not
> re-implement; extend in place if requirements change.

**What actually shipped:**

- `id` is a required top-level field in `margo.yaml`.
- `version` is a required top-level field — it is both the margo artifact OCI tag and
  `manifest.version` in templates. There is **no `margo:` block** — `directory`
  (default `margo`) and `repository` (global default, overridable per component) are
  top-level fields alongside `version`.
- `app.yaml.jinja` / `app.yaml` file resolution in `_build_margo`: both present → hard
  error; `.jinja` present → render with Jinja2 `StrictUndefined`, write as `app.yaml`,
  `.jinja` source removed from output; neither present → hard error; only `app.yaml` →
  copied verbatim, no substitution.
- Jinja2 template context (`build_jinja2_context` in `domain/metadata.py`, pure
  function, no Jinja2 import in `domain/`): `manifest.id`, `manifest.name`,
  `manifest.version`, `manifest.appVersion`, `manifest.description`,
  `manifest.directory`, `manifest.repository`, `manifest.annotations`,
  `manifest.author`, `manifest.organization`, `manifest.compose.*`,
  `manifest.quadlet.*`. No `manifest.margo` sub-object.
- Variant `version` is **optional**. When omitted, derived as
  `<component-version>+<type>-<variant-name>` (e.g. `2.1.0+compose-default` → OCI tag
  `2.1.0_compose-default`). Derivation happens at context-build/build time, not parse
  time — `VariantConfig.version` is stored as `str | None`.
- Variant `component` default: `{id}-{type}-{name}` (e.g. `myapp-compose-default`).
  Flat components (no `variants` declared) default to `{id}-{type}` (e.g.
  `com-example-nginx-quadlet`) and expose `tag`/`ref`/`component` directly on the
  component context, plus a single synthetic entry in `variants` for uniform iteration.
- Variant names colliding with reserved field names (`directory`, `repository`,
  `variants`, `version`, `tag`, `ref`, `component`) are rejected at parse time.
- Old `<app_tag>`/`<margo_tag>`/`<compose_tag>`/`<quadlet_tag>`/`<helm_chart_tag>`
  placeholder substitution is removed from the margo path entirely. It remains for
  compose/quadlet text files.
- `infra/filesystem.py` `substitute_placeholders` warns (does not fail) on any
  `<..._tag>` pattern left unresolved in compose/quadlet source text.
- `image: {search, replace}` block on `ComponentConfig` and `VariantConfig`
  (`domain/metadata.py`). `search` is a literal string. `replace` is a **Jinja2
  template string**, rendered in `services/build.py` with the same manifest context as
  `app.yaml.jinja` (`StrictUndefined` — undefined variable is a hard build error) before
  being handed to `infra/filesystem.py` as a plain resolved string (that module stays
  Jinja2-agnostic). Variant-level `image` fully overrides (not merges) the
  component-level one. Unmatched `search` string warns, does not fail.
- Directory default fixed: component `directory` (compose/quadlet) defaults to the
  component type name when absent, instead of raising an error.
- Parse error messages now name the failing component (e.g.
  `"'quadlet' variant missing required field 'name'"`).
- Top-level `repository` in `margo.yaml` is parsed and threaded through to
  `build_jinja2_context` as the fallback for components/variants with no repository
  override of their own.
- `BuildTarget` gained `artifact_path` — the actual artifact location (`.tgz` path for
  compose/quadlet, the output directory for margo) — so `margot build` output shows a
  meaningful path for every package type instead of a bare directory for margo.
- `jinja2` added to `pyproject.toml` dependencies.
- 501 tests passing, 97.15% coverage.

---

### Item 3 (original plan, superseded above) — Breaking refactor: `app.yaml` Jinja2 rendering

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
    search: "localhost/myapp:dev"                                 # exact literal string as it appears in the source file(s)
    replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}"  # Jinja2 template — rendered from manifest context
  variants:
    - name: default
      version: 1.0.0
      # inherits the component-level `image` block above (no override)
    - name: gpu
      version: 1.0.0_gpu
      image:                                                      # per-variant override — replaces, not merges
        search: "localhost/myapp:dev-gpu"
        replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}-gpu"
```

```yaml
quadlet:
  directory: quadlet
  version: 1.0.0
  image:
    search: "localhost/myapp:dev"
    replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}"
```

**Rules:**

1. **One `search`/`replace` pair per component (or per-variant override).** Multi-image
   support (project owner's decision) is achieved by declaring multiple components or
   variants — each with its own `image` block — not by a list of image mappings within
   one block. Keeps the mechanism format-agnostic: it's a literal string search against
   text files (no YAML-key-aware parsing of `image:` lines, which would require compose-
   and quadlet-specific parsers).
2. **`search` is a literal string**, not a regex. Matched and replaced across all text
   files in the component's source dir (respecting `.rsyncignore`, same as existing
   substitution).
3. **`replace` is a Jinja2 template string**, rendered with the same manifest context
   used for `app.yaml.jinja` (Item 3b), scoped to the enclosing component/variant (e.g.
   `{{ manifest.appVersion }}`, `{{ manifest.compose.repository }}`,
   `{{ manifest.compose.default.tag }}`). Rendered with `StrictUndefined` — same as
   `app.yaml.jinja` — so an undefined variable is a hard build-time error, not a silent
   empty string. This reuses the Jinja2 context/rendering machinery built for Item 3b
   rather than the plain-string placeholder map (`<app_tag>` etc.): the whole point of
   `image.replace` is that it stays in sync automatically when `appVersion` (or any other
   manifest field) is bumped — no separate edit to the `image` block itself.
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
- `replace` is stored as a raw template string — no rendering happens in `metadata.py`
  (pure parsing layer, no Jinja2 dependency here). Rendering happens in `services/build.py`
  using the same Jinja2 environment/context as `app.yaml.jinja` (Item 3b).

**`infra/filesystem.py` / `services/build.py` changes:**
- `services/build.py` renders each resolved `image.replace` template (Jinja2,
  `StrictUndefined`) using the manifest context *before* calling into the text
  substitution pass, then hands the fully-resolved `{search, replace}` pair (both plain
  strings at this point) to `infra/filesystem.py` for the literal string replace.
- `infra/filesystem.py` itself stays Jinja2-agnostic — it only ever receives resolved
  strings. It runs the image search/replace as part of the same text-substitution pass
  as placeholder substitution for compose/quadlet (not a separate walk).
- `services/build.py` resolves the effective `image` config per variant: variant's own
  `image` if present, else the component-level `image`, else none.

**Files touched (additive to the list below):**
- `src/margot/domain/metadata.py` — `ImageConfig`, `ComponentConfig.image`,
  `VariantConfig.image`, parsing + validation.
- `src/margot/infra/filesystem.py` — extend substitution pass to include image
  search/replace (receives pre-rendered strings only); unmatched-search warning.
- `src/margot/services/build.py` — resolve effective `image` config per variant/component,
  render `replace` via the shared Jinja2 environment/context (StrictUndefined), and pass
  the resolved `{search, replace}` pair into the substitution call for compose/quadlet
  builds.
- `tests/unit/test_metadata.py` — `ImageConfig` parsing, variant override, missing
  fields.
- `tests/unit/test_filesystem.py` — search/replace applied, unmatched search warns.
- `tests/integration/test_build.py` — end-to-end: component-level image sub, variant
  override, no `image` block declared (no-op), `replace` template rendering with
  manifest context, undefined Jinja variable in `replace` → hard error.
- **`FEATURES.md` update required** — add `image` block to the `margo.yaml` format
  reference (compose/quadlet sections) and to the Package Types section. This is new
  spec surface, not implementation detail — must land in `FEATURES.md` per
  `documentation.md` steering rules (spec first, docs follow). **Already done** —
  `FEATURES.md` documents `image.replace` as a Jinja2 template string rendered from the
  manifest context.

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

- [x] All three items implemented.
- [x] `uv run pytest` passes with no failures.
- [x] No `# TODO` markers left from this sprint's work.
- [x] All new code follows `code-conventions.md` (console output, imports, TODO format).
- [x] `ROADMAP.md` updated: Sprint 5 items moved to Completed Sprints table; backlog
  entries struck or removed.
- [x] Commits: `a5b03b0` (auth status), `2e5074a` (authenticated fetch/pull), and
  `249ea30`/`763b660`/`3001a94`/`d969ef0`/`11d3b11` (Jinja2 `app.yaml` refactor,
  landed as five logical commits rather than one — directory default fix, artifact
  path output, top-level repository fix, and the `margo:` block removal were each
  found and fixed post-initial-implementation, in response to real-world testing).

---

## Open questions / decisions locked

- **Breaking change strategy:** Jinja2 path and placeholder removal ship in the same
  sprint. No deprecation window (margot is pre-1.0, unpublished).
- **`component` field:** developer-owned, margot computes a default but never overwrites
  an explicit value. Stored in `VariantConfig` and surfaced in the template context.
- **Flat components in Jinja2 context:** always exposed as a single synthetic variant
  entry in `variants` so templates iterate uniformly regardless of layout.
- **No `margo:` block (decided post-implementation, during real-world testing):** the
  margo artifact's `directory`, `version`, and `repository` are top-level `margo.yaml`
  fields, not nested under a `margo:` key. `version` is required at the top level.
  Discovered via dogfooding — the original plan's `margo:` block was never implemented
  as a distinct concept in the docs site examples authored in parallel, and the docs
  site examples are the correct design.
- **Variant `version` optional (decided post-implementation):** omitting a variant's
  `version` derives it as `<component-version>+<type>-<variant-name>`. Only `name` is
  required per variant entry.
