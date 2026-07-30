# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

---

## Backlog / Stack (Sprint 5+)

Unordered within groups; sequencing decided at sprint planning.

### Display UX

- Minified JSON output + make minified the **default** display for artifacts
  (fetch may keep pretty as default — TBD).
- Table output when listing **multiple** URIs (new `list`-style command).

### Manifest recognition & validation (on JSON output)

- Detect & label: recognized margo manifest / valid / invalid / unknown OCI artifact.
- LinkML validation path (ties into `verify`).

### More artifact types in `fetch`

- image, compose component, quadlet component, helm chart.
- Extend `PackageType` enum + per-type display.

### Remaining commands

- `verify` (LinkML: local + `--remote`)

### `margot auth status` (new command — ships after Sprint 4 lands `auth login`/`auth logout`)

**Decision (locked):** subcommand group. CLI is `margot auth login`, `margot auth logout`,
`margot auth status`. The `auth` group is introduced in Sprint 4; `status` subcommand
ships in a later sprint.

**Problem:** there is currently no way to inspect the auth state without attempting a
registry operation and seeing it fail. Developers need a quick sanity check before a
push, especially given ECR's 12-hour token TTL.

**What it should show:**

- For each registry tracked in `~/.config/margot/credentials.toml`: registry hostname,
  expiry timestamp, time remaining (or EXPIRED), and a clear VALID / EXPIRING / EXPIRED
  status label.
- If no credentials are tracked, say so rather than showing an empty table.
- Credentials stored by oras-py in the Docker/Podman credential store but not tracked
  by margot (no `--save-expiry` used) should be noted as "present but expiry unknown".

**Constraint:** read-only command — no network calls, no mutation. Pure display from
`~/.config/margot/credentials.toml` and the oras-py credential store.

---

### Placeholder substitution — review, extend, and `app.yaml` generation

**Two distinct problems that share a sprint:**

#### 1. Compose / quadlet s-n-r: incomplete coverage

**Problem:** the current plain string-replace approach works but may have gaps —
placeholder coverage has not been formally specified or tested against real-world
compose/quadlet files. Edge cases (multi-line values, quoted strings, nested YAML
anchors) are untested.

**Constraint:** for compose and quadlet, plain string replace on text files is the right
model — developers work with real, runnable files that contain placeholders, and `build`
produces the shippable tarball. The engine should stay simple. What needs work is:

- A formal, tested list of all supported placeholders and their resolved values.
- Confidence that substitution handles common YAML formatting patterns correctly.
- Clear error or warning when a placeholder in a file has no declared value.

#### 2. Margo `app.yaml`: from opaque template to structured generation

**Problem:** `app.yaml` contains two distinct zones — a structural scaffold (id,
description, deploymentProfile, components list) that margot can *compute* from
`margo.yaml` declarations, and variable parts (parameters, their types, defaults,
validation schema) that the developer owns. Today margot treats the whole file as opaque
and does string replace across it. This breaks down when structural fields need to be
derived from `margo.yaml` (e.g. components referencing artifact versions) and gives
developers no framework for declaring typed parameters.

**Constraint:** `app.yaml` stays hand-authored in the `margo/` directory — margot does
not own the file. The developer authors the parts they control; margot augments or
overwrites the structural parts it can compute at build time. The two zones must be
cleanly separable.

**Decision (locked):** Jinja2, with an optional `margo/app.yaml.jinja` template file.

**File resolution:**

- `app.yaml.jinja` present → rendered against a context derived from `margo.yaml`, output
  written as `app.yaml` in the build dir. The `.jinja` source MUST NOT ship in the artifact.
- `app.yaml.jinja` absent → `app.yaml` is required and copied **verbatim**. Fully static,
  no substitution.
- Both present → hard error. The render would otherwise silently clobber the copied file.

Rendering uses Jinja2 `StrictUndefined` so an undefined variable fails the build naming the
variable, rather than emitting empty YAML.

**Template context** (derived from `margo.yaml`, read-only):

```text
manifest.id  manifest.name  manifest.version  manifest.appVersion  manifest.description  manifest.annotations  manifest.author  manifest.organization
manifest.margo.version  manifest.margo.tag  manifest.margo.ref  manifest.margo.repository  manifest.margo.directory
manifest.compose.directory  manifest.compose.repository
manifest.compose.variants                      # ordered list of variant objects
manifest.compose.<variant-name>                # direct access, e.g. manifest.compose.minimal.tag
manifest.quadlet.*                             # same shape
```

Variant object: `name`, `version`, `tag`, `ref`, `repository`, `component`.

- `version` is optional. Default: `<component-version>+<type>-<variant-name>` (e.g. for a
  compose component at version `2.1.0` with variant `minimal`, the derived version is
  `2.1.0+compose-minimal`). As authored it uses `+`; `tag` is the OCI-safe form with `_`.
  `ref` is `repository:tag`. `tag` and `ref` are **computed and not authorable** — enforced
  by strict schema (unknown keys in `margo.yaml` are rejected).
- `component` (the Margo component name) is **developer-owned**. margot supplies a valid
  default of `<id>-<type>-<variant-name>` and never rewrites a value the developer sets.
- Flat components (no `variants`) still expose a single synthetic entry in `variants`, so
  templates iterate identically in both modes.
- Variant names that collide with component field names (`directory`, `repository`,
  `variants`, `version`, `tag`, `ref`, `component`) MUST be rejected at parse time.

**Deferred (additive, second pass):** a `| to_yaml(indent=N)` filter fed by pre-rendered
deployment-profile fragments. Pass 1 renders a developer-authored profile template per
variant and parses it into structured data; pass 2 splices it via the filter. This keeps
profile *shape* owned by the developer while collapsing the YAML-indentation hazard to a
single filter call. Not required for the first cut.

**Rejected alternatives:**

- **Plain string replace (extended):** cannot address per-variant tags, so a project with
  two compose variants must hardcode the second one — the duplicate-source-of-truth bug
  this work exists to fix. No loops, no conditionals.
- **Hybrid generation + merge:** requires margot to own the deployment-profile schema and a
  defined deep-merge strategy. The deferred two-pass render achieves the same ergonomics
  without transferring shape ownership away from the developer.
- **Helm-style Go templates reimplemented in Python:** reinventing Jinja2 with worse
  ergonomics.

#### 3. Breaking refactor — `app.yaml` placeholders removed

**Impact: breaking.** Bundled with the change above, and the reason this work is a refactor
rather than a feature.

- `<app_tag>`, `<margo_tag>`, `<compose_tag>`, `<quadlet_tag>`, `<helm_chart_tag>` are
  removed from the `app.yaml` path entirely. A static `app.yaml` is copied verbatim;
  projects relying on substitution inside it break and must migrate to `app.yaml.jinja`.
- These placeholders **remain** for compose/quadlet text files, where plain string replace
  is still the right model (see item 1).
- `<helm_chart_tag>` is dropped as a concept. It resolves to an empty string today, and
  margot does not build Helm charts — chart revisions are literals the developer authors.
- `id` moves into `margo.yaml` as a required top-level field. It currently exists only in
  `app.yaml`, but the template context needs it and it is the base for derived component
  name defaults.

margot is pre-1.0 and unpublished, so the clean break is preferred over a compatibility
shim. No deprecation window.

---

### Cross-cutting

- Authenticated `fetch` / `pull` against private ECR (after auth lands in Sprint 4)
- ~~`domain/tags.py` OCI tag + SemVer validation~~ ✓ done (Sprint 3)
- ~~`domain/metadata.py` `margo.yaml` project descriptor parsing~~ ✓ done (Sprint 3)
- ~~`config.py` full dynaconf layering~~ ✓ done (Sprint 3)
- ~~**Update FEATURES.md** `fetch` section: positional URI + raw JSON~~ ✓ done

---

## Completed Sprints

| Sprint | Capability | Release |
| -------- | ----------- | --------- |
| Sprint 1 | `margot fetch` — anonymous OCI manifest retrieval, pretty-printed JSON output, URI validation, `margot --version` | [0.1.0](https://github.com/karnarokEpoch/margot/releases/tag/0.1.0) |
| Sprint 2 | `margot pull` — anonymous OCI artifact pull to disk, artifact type detection via `artifactType`, layer naming (title annotation → manifest-level fallback), `--force` override for unknown types, shared `domain/uri.py` | — |
| Sprint 3 | `margot build` — local artifact build for margo/compose/quadlet package types, placeholder substitution (`<app_tag>` from `appVersion`, `<margo_tag>`, `<compose_tag>`, `<quadlet_tag>`), variant support, idempotent output dir, multi-type `-t` flag, `margo.yaml` project descriptor, dynaconf config layering, pure-Python filesystem ops | — |
| Sprint 4 | `margot auth login` / `margot auth logout` + `margot push` — OCI registry authentication via oras-py (`margot auth` subcommand group), credential expiry tracking (`~/.config/margot/credentials.toml`), proactive expiry check before registry ops, push built artifacts (margo/compose/quadlet) with correct `artifactType`, media types, and OCI annotations, SemVer gate before push, multi-type + variant support mirroring build | — |
