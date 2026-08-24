# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

---

## Planned Sprints

### Sprint 6 — `margot verify`

**Goal:** Ship a complete `margot verify` command: local-only LinkML validation against
the upstream Margo spec schema (always-on) and an opt-in (`--recommend`) margot-curated
recommended schema, plus an opt-in (`--deep`) structured rich display of the full
`app.yaml` state. Default output (no flags) is plain CI-check-style pass/fail. Remote
artifact reachability checking is descoped to the backlog (see Backlog → Remaining
commands above).

**Prerequisite:** Sprint 5 is merged (✅ complete — see Completed Sprints below). `id`
field is in `margo.yaml`, `domain/metadata.py` is final, and the Jinja2 build path is
stable.

**Full plan:** see [`.kiro/sprints/sprint-6.md`](.kiro/sprints/sprint-6.md) — background
on the two LinkML schemas, all five scope items (validation infra, vendored schemas,
`services/verify.py`, parameter inspection display, CLI wiring), definition of done, and
locked decisions. Ships in **4 phases**: (1) Schema A vendored + minimal `verify` command
against it, (2) `--deep` display + full CLI flags, (3) author Schema B + wire
`--recommend`, (4) polish/DoD closure. Key locked decisions:

- Schema A (upstream, vendored) always runs; Schema B (recommended, curated) only runs
  with `--recommend`. When both run, output clearly separates findings under labeled
  Schema A / Schema B sections.
- Default output is plain pass/fail (CI-check style). `--deep` enables the rich panel
  display (Application / Components / Parameters).
- `verify` is local-only this sprint — no `--remote`, no network calls. Remote
  reachability check is backlog (see above).
- Vendored Schema A file states its pinned commit and that the Margo spec is still
  draft; `verify` output surfaces this so results aren't mistaken for a stable-spec check.
- Parameters panel reads the top-level `parameters` map (confirmed against the upstream
  schema, not `deploymentProfile.parameters`), joined with `configuration.schema` via
  `configuration.sections[].settings[]` for constraints.

---

## Backlog / Stack (Sprint 7+)

Unordered within groups; sequencing decided at sprint planning.

### Display UX

- Minified JSON output + make minified the **default** display for artifacts
  (fetch may keep pretty as default — TBD).
- Table output when listing **multiple** URIs (new `list`-style command).

### Manifest recognition & validation (on JSON output)

- Detect & label: recognized margo manifest / valid / invalid / unknown OCI artifact.

### More artifact types in `fetch`

- image, compose component, quadlet component, helm chart.
- Extend `PackageType` enum + per-type display.

### Remaining commands

- `verify --remote` — remote artifact reachability check, descoped from Sprint 6
  (local-only `verify` ships in Sprint 6). For each component ref in `margo.yaml`,
  call `OrasClient.get_manifest(ref)`, report REACHABLE / MISSING / WRONG_TYPE, with
  `check_credentials(hostname)` before each call. Open question carried over: whether
  variant tags are also checked or only primary versions.

---

### Cross-cutting

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
| Sprint 5 | `margot auth status` (credential expiry table), authenticated `fetch`/`pull` (transparent oras-py credential use), and the Jinja2 `app.yaml.jinja` rendering refactor: `id`/`version` required top-level fields, no `margo:` block (top-level `directory`/`repository` for the margo artifact instead), optional variant `version` with `<base>+<type>-<name>` derivation, `image: {search, replace}` block for compose/quadlet dev-local image swapping (`replace` is a Jinja2 template rendered with `StrictUndefined`), unresolved-placeholder warnings, per-component error messages. See [`.kiro/sprints/sprint-5.md`](.kiro/sprints/sprint-5.md) for what shipped vs. the original plan. | — |
