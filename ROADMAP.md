# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

---

## Planned Sprints

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
* Past that gate it renders whatever the spec permits, faithfully — a parameter no
  `Setting` references, a component with no `repository`, a profile with no components all
  show up as-is. Judging them is `verify`'s job.
* Rich `Panel` / `Tree` blocks, full-width and stacked (no `Columns`): identity+catalog
  (`apiVersion` as title, `Catalog: None` when absent), deployment profiles
  (→ per-profile `requiredResources` → components → properties, `type` printed verbatim
  so margot's `quadlet` profile renders even though upstream still pins `helm|compose`),
  and one configuration tree carrying section → setting → schema → parameter → pointer →
  components. `--section` filters which blocks appear, never their order.
* **No parameters block** — parameters are reached through configuration, in the order a
  reviewer thinks: what can be configured, what validates it, what it defaults to, where
  it lands. Each pointer shows `(n/total)` against the count of distinct declared
  components.
* Coherence signals that fall out of the join for free — `(n/total)` ratios,
  `(not declared)` / `(not defined)` markers, a trailing unreferenced-parameters subtree —
  ship with it. A summarising Observations panel and anything with a severity or exit code
  remain deliberately **out** of this sprint.

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
  (local-only `verify` shipped in Sprint 6 — see Completed Sprints). For each component
  ref in `margo.yaml`, call `OrasClient.get_manifest(ref)`, report REACHABLE / MISSING /
  WRONG_TYPE, with `check_credentials(hostname)` before each call. Open question carried
  over: whether variant tags are also checked or only primary versions.

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
| Sprint 6 | `margot verify` — local-only LinkML validation of the Margo application description (`app.yaml`, or `app.yaml.jinja` rendered to a temp file, never requiring a prior `build`), upstream Margo spec schema vendored at draft commit `45f4359` with that commit reported in the output, curated recommended schema (`--recommend`) as a lint pass and `--strict` as a contract, `--only-recommend` to lint against the recommended schema alone, `--schema` / `--recommended-schema` overrides, `validation/` LinkML adapter layer (plugin set + finding formatter, `x-placeholder-extensions` stripped so vendor content never false-fails), Jinja2 rendering extracted to `infra/templating.py` and shared with `build`, standalone descriptor resolution reused by `describe`, plain CI-style pass/fail output | — |
