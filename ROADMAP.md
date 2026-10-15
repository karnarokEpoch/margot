# margot — Roadmap

Forward register: planned features, fixes to make, ideas, and backlog. A queue of intent, not a spec.

The authority model:

- **ROADMAP.md** (this file) — what to build next.
- **`.kiro/sprints/sprint-N.md`** — authoritative design while a release is being built; deleted on close-out.
- **`docs/`** — standing source of truth for shipped behavior.
- **Git history** — archives of each sprint's design decisions via close-out commits.

---

## Planned Sprints

### Sprint 10 — `--json` output and stable error codes

Makes margot's output and failure modes machine-consumable for scripts/agents: `--json`
on `describe` and `verify` (their display/result dataclasses already have zero `rich`
coupling), a stable, closed exit-code taxonomy replacing today's single `Exit(1)`
catch-all across 22 call sites, a structured `--json` error envelope on stderr, and
explicit `--no-color`/`NO_COLOR` support. No change to default rich rendering. Full plan
at [`.kiro/sprints/sprint-10.md`](.kiro/sprints/sprint-10.md).

### Sprint 11 — Margo resource media types driven by `app.yaml`

Fixes two correctness bugs found in manual testing: `margot push` dropping any resource
file that isn't exactly one of four hardcoded filenames (e.g. an `icon.svg` instead of
`icon.png` was silently never shipped), and `describe`/`verify`/`pull --recursive`
locating the descriptor layer by the literal filename `app.yaml` instead of its OCI
`mediaType`, which fails on valid artifacts produced by tooling other than margot. Resource
discovery becomes driven by `app.yaml`'s own fields (`icon`, `descriptionFile`,
`licenseFile`, `releaseNotes`), typed by the file's real extension with no allow-list
(generic passthrough, e.g. `+svg`, `+bmp`); any other file under `resources/` ships with
an `application/octet-stream` fallback type. Descriptor-layer lookup becomes
`mediaType`-based with a warning (first match wins) if more than one candidate layer is
present. Full plan at [`.kiro/sprints/sprint-11.md`](.kiro/sprints/sprint-11.md).

### Sprint 12 — Local descriptor fallback resolution (no `margo.yaml` required)

Lets `margot describe` and `margot verify` run directly against a directory holding a
bare, static `app.yaml` (e.g. produced by `margot pull`) with no `margo.yaml` present —
silently, no new flag. Fallback search order: `<project_dir>/app.yaml`, then
`<project_dir>/margo/app.yaml`; static-only, no Jinja2 (a `.jinja` found in fallback mode
is an actionable error, since rendering requires `margo.yaml`'s context). `pull` itself is
explicitly unchanged — it stays a simple layer dump, no synthesized files. Full plan at
[`.kiro/sprints/sprint-12.md`](.kiro/sprints/sprint-12.md).

### Sprint 13 — `margot.yaml` project file and `margot migrate`

Five items in one sprint. (1) `fix(pull)`: sanitise component names in `pull --recursive`
(shippable first as a patch). (2) The project descriptor is renamed `margo.yaml` →
`margot.yaml` (same content, `apiVersion: v1`; margot's own file, not part of the Margo
standard); legacy `margo.yaml` is read with a deprecation warning until 1.0.0, and
`margot migrate` renames it. (3) Per-variant `repository` in `margot.yaml`. (4) `margot
migrate` adopts an existing manifest — typically after `margot pull --recursive` — in the
current folder by default (`--output` for elsewhere): `margot.yaml` plus the `margo/` layout,
`app.yaml` copied verbatim and static, `name` = `metadata.name`; `--dry-run`, `--force`,
nothing left behind when migrating in place. (5) `margot migrate --components` declares
compose/quadlet components 1:1 as variants and organises their sources into `compose/` /
`quadlet/` (local `pull -r` archives first, registry otherwise; safe extraction; one
repository per type unless `--all-repositories`; helm warned, not representable). Depends on
Sprints 11 and 12. Full plan at [`.kiro/sprints/sprint-13.md`](.kiro/sprints/sprint-13.md).

---

## Backlog / Stack (Sprint 14+)

Unordered within groups; sequencing decided at sprint planning.

### Display UX

- Minified JSON output + make minified the **default** display for artifacts
  (`console.print_json` is still pretty-printed; fetch may keep pretty as default — TBD).
- Table output when listing **multiple** URIs (new `list`-style command).
- `--json` for the action commands `build`, `push`, `pull` (deferred from Sprint 10, which
  only covers `describe` and `verify`). Revisit once Sprint 10's pattern is proven.

### Manifest recognition in `fetch`

- `verify` / `describe` already validate and render Margo descriptors, locally and from an
  OCI URI (Sprints 6–9); what is missing is `fetch` *classifying* what it prints:
  recognised margo manifest / compose / quadlet component / unknown OCI artifact.

### More artifact types

- `pull` already detects margo, compose and quadlet via `artifactType`; `fetch` prints the
  raw manifest for anything. Remaining: detect image and helm chart artifacts — extend
  `PackageType` (no `HELM`/`IMAGE` members today) with per-type handling and display.

### Cross-cutting

- `margot init` — scaffold a new Margo project: generate a starter `margot.yaml` and the
  expected directory layout (`margo/app.yaml.jinja`, optional `compose/` / `quadlet/`).
  The command does not exist yet. Sprint 13 reworks the "project file not found" error hint
  to point at `margot migrate`; once `init` lands, mention it there too.
- `margot migrate` — now scheduled as Sprint 13 (see Planned Sprints).
- `migrate` follow-up (low priority, owner prefers static `app.yaml`): partial reverse
  templating — only the few fields `margot.yaml` manages (`id`, `version`, component
  `repository`/`revision`, catalog), everything else verbatim. Acceptance: render the
  template with the generated `margot.yaml` and compare parsed YAML to the source.
- **chore:** remove the legacy `margo.yaml` read path at **1.0.0** (deprecated in Sprint 13);
  and rename the internal `MargoYaml` / `load_margo_yaml` identifiers to match `margot.yaml`.
- Scheduled in Sprint 13 (no longer backlog): `pull --recursive` component-name
  sanitisation (Item 1, may ship as an earlier patch) and per-variant `repository` (Item 3).

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
| Sprint 9 | Remote OCI inspection for `describe` and `verify` (optional positional URI, shared fetch/pull path); `margot package` offline bundle command with OCI image inclusion (`--no-images`, `--runtime`, `--platform`); Docker Hub normalization (`docker.io` → `registry-1.docker.io`, `library/` prefix for official images); attestation manifest filtering for multi-arch indexes. | [0.9.0](https://github.com/karnarokEpoch/margot/releases/tag/0.9.0) |
