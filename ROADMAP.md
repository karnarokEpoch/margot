# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

---

## Planned Sprints

### Sprint 5 — Jinja2 build refactor + auth polish

**Goal:** Ship the Jinja2 `app.yaml` rendering pipeline (breaking refactor), `margot auth
status`, authenticated `fetch`/`pull`, and the `image` search/replace block for
compose/quadlet dev-local image swapping.

**Full plan:** see [`.kiro/sprints/sprint-5.md`](.kiro/sprints/sprint-5.md) — all three
items (`auth status`, authenticated fetch/pull, Jinja2 `app.yaml` refactor including the
`image` search/replace design), file lists, and definition of done. Implementation order:
Items 1 (`auth status`) and 2 (authenticated fetch/pull) run in parallel worktrees — they
touch disjoint files (`infra/credentials.py`/`services/auth.py`/`commands/auth.py` vs.
`infra/oci.py`/`services/fetch.py`/`services/pull.py`). Item 3 (Jinja2 refactor + `image`
block) starts once both are merged.

**Status:** Item 2 (authenticated `fetch`/`pull`) is ✅ **done** — see
[`.kiro/sprints/sprint-5.md`](.kiro/sprints/sprint-5.md#item-2--authenticated-fetch-and-pull--done)
for the commit reference. Items 1 and 3 remain open; sprint is not yet complete.

Key locked decisions:

- Breaking change, no deprecation window (margot is pre-1.0, unpublished): old
  `<app_tag>`/`<margo_tag>`/`<compose_tag>`/`<quadlet_tag>`/`<helm_chart_tag>`
  placeholders are removed from the `app.yaml` path; `app.yaml.jinja` (Jinja2,
  `StrictUndefined`) replaces them. These placeholders remain for compose/quadlet text
  files, where plain string replace is still the right model.
- `id` becomes a required top-level field in `margo.yaml`.
- New optional `image: {search, replace}` block per component/variant in `margo.yaml` —
  `search` is a literal string (not regex) matched against compose/quadlet source text
  files at build time; `replace` is a **Jinja2 template** rendered from the same manifest
  context as `app.yaml.jinja` (`StrictUndefined` — undefined variable is a hard error).
  Keeps the checked-in source a real, runnable file locally (with a real dev image ref)
  while `build` swaps in the environment-appropriate ref, and keeps `image.replace` in
  sync automatically when `appVersion` (or any other manifest field) is bumped — no
  separate edit to the `image` block itself. Variant-level `image` fully overrides the
  component-level one (not merged). Optional — components with no dev-local image to
  swap declare nothing. Already reflected in `FEATURES.md`.

---

### Sprint 6 — `margot verify`

**Goal:** Ship a complete `margot verify` command: local-only LinkML validation against
the upstream Margo spec schema (always-on) and an opt-in (`--recommend`) margot-curated
recommended schema, plus an opt-in (`--deep`) structured rich display of the full
`app.yaml` state. Default output (no flags) is plain CI-check-style pass/fail. Remote
artifact reachability checking is descoped to the backlog (see Backlog → Remaining
commands above).

**Prerequisite:** Sprint 5 must be merged. `id` field is in `margo.yaml`,
`domain/metadata.py` is final, and the Jinja2 build path is stable.

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

### Known issues

- `margot auth logout` does not remove the credential entry from the oras-py/Docker
  credential store (`~/.docker/config.json`) — `oras.auth.base.AuthBackend.logout()`
  only mutates its in-memory `_auth_config`; nothing in oras-py ever persists that
  removal back to disk (confirmed: no `save`/`write_json` call anywhere in the logout
  path, in any auth backend — `basic`, `token`, or `ecr`). `margot auth login` "works"
  today only because it delegates to the `docker` Python SDK's own `client.login()`,
  which writes the file as a side effect; there is no equivalent for logout. Fix
  requires margot to implement its own removal (read `~/.docker/config.json`, delete
  the `auths` entry incl. localhost variants, write back) rather than relying on
  oras-py. Deferred — revisit alongside or after Sprint 5 Item 1 (`auth status`).

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
