# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

---

## Planned Sprints

### Sprint 6 — `margot verify`

**Goal:** Ship a complete `margot verify` command: local-only LinkML validation of the
Margo application description (`app.yaml`, or `app.yaml.jinja` rendered to a temp file)
against the upstream Margo spec schema (always-on) and an opt-in (`--recommend`)
margot-curated recommended schema. Output is plain CI-check-style pass/fail. Remote
artifact reachability checking is descoped to the backlog (see Backlog → Remaining
commands above).

**Prerequisite:** Sprint 5 is merged (✅ complete — see Completed Sprints below). `id`
field is in `margo.yaml`, `domain/metadata.py` is final, and the Jinja2 build path is
stable.

**Full plan:** see [`.kiro/sprints/sprint-6.md`](.kiro/sprints/sprint-6.md) — background
on the two LinkML schemas, all four scope items (validation infra, vendored schemas,
`services/verify.py`, CLI wiring), layering/output rules, definition of done, and locked
decisions. Ships in **3 phases, one PR and one commit each**: (1) Schema A vendored +
`verify` command against it, (2) author Schema B + wire `--recommend`, (3) polish/DoD
closure. Key locked decisions:

* The command verifies the **application description** (`app.yaml` / `app.yaml.jinja`),
  not `margo.yaml`. Templated descriptors are rendered to a temp file with the same
  context `build` uses; `verify` never reads `<build_dir>` and never needs a prior build.
* Schema A (upstream, vendored) always runs; Schema B (recommended, curated) only runs
  with `--recommend`. When both run, output clearly separates findings under labeled
  Schema A / Schema B sections.
* Schema B is a lint pass by default (findings reported, exit code unaffected) and a
  contract with `--strict` (any finding exits 1).
* `verify` is local-only this sprint — no `--remote`, no network calls. Remote
  reachability check is backlog (see above).
* Output is plain pass/fail lines only — no tables, no panels, no `--deep`. The structured
  visual view became its own command, `margot describe` (Sprint 7).
* Vendored Schema A file states its pinned commit and that the Margo spec is still
  draft; `verify` prints this by default so results aren't mistaken for a stable-spec check.
* Descriptor resolution (find → render → load) ships as a standalone reusable function —
  `describe` calls it unchanged in Sprint 7.
* No example/golden `app.yaml` is shipped this sprint — users act on the warnings and
  errors `verify` reports.

---

### Sprint 7 — `margot describe`

**Goal:** Ship `margot describe`: a read-only, purely visual view of the Margo application
description — rich panels, trees and tables organizing the raw descriptor for human
review. The spirit of `kubectl describe`, rendered with boxes rather than flat text.

**Prerequisite:** Sprint 6 merged — `describe` reuses its descriptor resolution function
and `infra/templating.py` unchanged.

**Full plan:** see [`.kiro/sprints/sprint-7.md`](.kiro/sprints/sprint-7.md). Key locked
decisions:

* Split out of `verify`'s original `--deep` flag: `verify` answers "is this shippable?"
  (plain lines, exit code, CI), `describe` answers "what is in here?" (visual, exit 0).
* No `--check` flag and no `linkml` in this command's path — `describe` never validates.
* No `--json` / `--yaml` / plain-text mode. Visual output only.
* Refuses rather than degrades: missing descriptor, both `app.yaml` and `app.yaml.jinja`
  present, unresolved Jinja2 variable, unparseable YAML, or `kind` not
  `ApplicationDescription` → exit 1 pointing at `margot verify`. No other edge-case
  handling.
* Past that gate it renders whatever the spec permits, faithfully — an orphan parameter, a
  component with no `repository`, a profile with no components all show up as-is. Judging
  them is `verify`'s job.
* Rich `Panel` / `Columns` / `Tree` / `Table` blocks: identity, catalog, deployment
  profiles (→ components → properties, no `quadlet` type exists in the Margo spec),
  parameters (top-level `parameters` map joined with `configuration.schema` via
  `configuration.sections[].settings[]`), configuration layout, and
  `x-placeholder-extensions` when present. `--section` limits the output.
* Coherence observations (orphan parameters, targets naming unknown components) are an
  open idea, deliberately **not** designed this sprint.

---

## Backlog / Stack (Sprint 8+)

Unordered within groups; sequencing decided at sprint planning.

### Display UX

* Minified JSON output + make minified the **default** display for artifacts
  (fetch may keep pretty as default — TBD).
* Table output when listing **multiple** URIs (new `list`-style command).

### Manifest recognition & validation (on JSON output)

* Detect & label: recognized margo manifest / valid / invalid / unknown OCI artifact.

### More artifact types in `fetch`

* image, compose component, quadlet component, helm chart.
* Extend `PackageType` enum + per-type display.

### Remaining commands

* `verify --remote` — remote artifact reachability check, descoped from Sprint 6
  (local-only `verify` ships in Sprint 6). For each component ref in `margo.yaml`,
  call `OrasClient.get_manifest(ref)`, report REACHABLE / MISSING / WRONG_TYPE, with
  `check_credentials(hostname)` before each call. Open question carried over: whether
  variant tags are also checked or only primary versions.

---

### Cross-cutting

* ~~`domain/tags.py` OCI tag + SemVer validation~~ ✓ done (Sprint 3)
* ~~`domain/metadata.py` `margo.yaml` project descriptor parsing~~ ✓ done (Sprint 3)
* ~~`config.py` full dynaconf layering~~ ✓ done (Sprint 3)
* ~~**Update FEATURES.md** `fetch` section: positional URI + raw JSON~~ ✓ done

---

## Completed Sprints

| Sprint | Capability | Release |
| -------- | ----------- | --------- |
| Sprint 1 | `margot fetch` — anonymous OCI manifest retrieval, pretty-printed JSON output, URI validation, `margot --version` | [0.1.0](https://github.com/karnarokEpoch/margot/releases/tag/0.1.0) |
| Sprint 2 | `margot pull` — anonymous OCI artifact pull to disk, artifact type detection via `artifactType`, layer naming (title annotation → manifest-level fallback), `--force` override for unknown types, shared `domain/uri.py` | — |
| Sprint 3 | `margot build` — local artifact build for margo/compose/quadlet package types, placeholder substitution (`<app_tag>` from `appVersion`, `<margo_tag>`, `<compose_tag>`, `<quadlet_tag>`), variant support, idempotent output dir, multi-type `-t` flag, `margo.yaml` project descriptor, dynaconf config layering, pure-Python filesystem ops | — |
| Sprint 4 | `margot auth login` / `margot auth logout` + `margot push` — OCI registry authentication via oras-py (`margot auth` subcommand group), credential expiry tracking (`~/.config/margot/credentials.toml`), proactive expiry check before registry ops, push built artifacts (margo/compose/quadlet) with correct `artifactType`, media types, and OCI annotations, SemVer gate before push, multi-type + variant support mirroring build | — |
| Sprint 5 | `margot auth status` (credential expiry table), authenticated `fetch`/`pull` (transparent oras-py credential use), and the Jinja2 `app.yaml.jinja` rendering refactor: `id`/`version` required top-level fields, no `margo:` block (top-level `directory`/`repository` for the margo artifact instead), optional variant `version` with `<base>+<type>-<name>` derivation, `image: {search, replace}` block for compose/quadlet dev-local image swapping (`replace` is a Jinja2 template rendered with `StrictUndefined`), unresolved-placeholder warnings, per-component error messages. | — |
