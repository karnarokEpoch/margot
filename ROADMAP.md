# margot — Roadmap

Forward register: planned features, fixes to make, ideas, and backlog. A queue of intent, not a spec.

The authority model:
- **ROADMAP.md** (this file) — what to build next.
- **`.kiro/sprints/sprint-N.md`** — authoritative design while a release is being built; deleted on close-out.
- **`docs/`** — standing source of truth for shipped behavior.
- **Git history** — archives of each sprint's design decisions via close-out commits.

---

## Planned Sprints

### Sprint 9 — Shared remote OCI resolution for `describe` and `verify`

`describe` and `verify` gain the same optional positional OCI URI. Without it, both
commands preserve local-project behavior; with it, both reuse the shared `fetch`/`pull`
validation, credential, artifact-type, and layer-download path to pull a margo artifact
into a temporary directory, then run their existing local descriptor pipeline against
its `app.yaml`. This completes the unshipped remote `describe` design and replaces the
reachability-only `verify --remote` backlog proposal. Read-only registry inspection
accepts arbitrary existing OCI tags; no SemVer gate. Full plan at
[`.kiro/sprints/sprint-9.md`](.kiro/sprints/sprint-9.md).

### Sprint 10 — `--json` output and stable error codes

Makes margot's output and failure modes machine-consumable for scripts/agents: `--json`
on `describe` and `verify` (their display/result dataclasses already have zero `rich`
coupling), a stable, closed exit-code taxonomy replacing today's single `Exit(1)`
catch-all across 22 call sites, a structured `--json` error envelope on stderr, and
explicit `--no-color`/`NO_COLOR` support. No change to default rich rendering. Full plan
at [`.kiro/sprints/sprint-10.md`](.kiro/sprints/sprint-10.md).

---

## Backlog / Stack (Sprint 11+)

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

### Cross-cutting

* ~~`margot push --dry-run` — validate readiness without pushing, `Dry run OK: ...` output~~
  ✓ done (post-Sprint 4, unplanned addition)
* ~~`domain/tags.py` OCI tag + SemVer validation~~ ✓ done (Sprint 3)
* ~~`domain/metadata.py` `margo.yaml` project descriptor parsing~~ ✓ done (Sprint 3)
* ~~`config.py` full dynaconf layering~~ ✓ done (Sprint 3)
* ~~**Update docs** `fetch` section: positional URI + raw JSON~~ ✓ done

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
| Sprint 7 | `margot describe` — read-only visual view of the Margo application description with rich panels and trees organizing the raw descriptor for human review. Identity+catalog panel with apiVersion title, deployment profiles with per-profile components and properties, and configuration-first join tree (section → setting → schema/parameter → pointer → components). Renders `type` verbatim (supports `quadlet` ahead of upstream spec), shows per-pointer component ratios against deduplicated component index, unreferenced-parameters subtree, scalar values in literal form (quoted strings, bare numbers, empty string as `""`, absent as `—`). No validation, no `linkml` import, exit 0 always except unloadable descriptor (exit 1). | — |
| Sprint 8 | `describe` component-first view (`--section component-first`, mirroring Sprint 7's section-first walk) and `--section config` renamed to `--section config-first` (no alias); read-only orphan/dead-end detection (`--section orphans`: unreferenced parameters, unresolved schema references, unused schemas, dangling component pointers); documented shell completion setup (`README.md`, `docs/index.md`). No validation exit paths added — stays inside `describe`'s existing read-only contract. | [0.8.0](https://github.com/karnarokEpoch/margot/releases/tag/0.8.0) |
