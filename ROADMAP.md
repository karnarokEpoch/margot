# margot — Roadmap

Forward register: planned features, fixes to make, ideas, and backlog. A queue of intent, not a spec.

The authority model:

- **ROADMAP.md** (this file) — what to build next.
- **`.kiro/sprints/sprint-N.md`** — authoritative design while a release is being built; deleted on close-out.
- **`docs/`** — standing source of truth for shipped behavior.
- **Git history** — archives of each sprint's design decisions via close-out commits.

---

## Planned Sprints

### Sprint 11 — Margo resource media types driven by `app.yaml`

Fixes two correctness bugs found in manual testing: `margot push` dropping any resource
file that isn't exactly one of four hardcoded filenames (e.g. an `icon.svg` instead of
`icon.png` was silently never shipped), and `describe`/`verify`/`pull --recursive`
locating the descriptor layer by the literal filename `app.yaml` instead of its OCI
`mediaType`, which fails on valid artifacts produced by tooling other than margot. Resource
discovery becomes driven by `app.yaml`'s own fields (`icon`, `descriptionFile`,
`licenseFile`, `releaseNotes`), typed by the file's format per the Margo spec (`.jpg` →
`+jpeg`, `.md` → `+markdown`, any other extension passed through, e.g. `+svg`, `+txt`);
the license type is the spec's `licenseFile` name and every resource layer carries the
`org.margo.app.resource` annotation. Any other file under `resources/` ships with
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

### Sprint 13 — `margot install`

Installs one **quadlet** deployment profile of a Margo application on the local host (rootless
Podman + systemd user session is the reference environment). `margot install [URI] [--project-dir]
[--build-dir] [--profile ID] [--set NAME=VALUE] [--yes] [--dry-run]` takes three sources — a built
margot project, a static folder (`app.yaml` + component archives, e.g. from `pull --recursive`, not
adopted by `migrate`), or a remote margo artifact, **including artifacts not produced by margot**
(resolution relies on the Margo spec and OCI metadata, never on margot-only conventions).
Everything is resolved, staged and checked (Quadlet generator dry-run) before the host is touched;
the plan is shown and confirmed (`--yes`, `--dry-run`). Delivered in three reviewed steps. **Step
1:** the quadlet files are placed in `~/.config/containers/systemd/<application-id>/` (with an
ownership marker) and systemd is reloaded; `install` never starts anything, it prints the
`systemctl --user start` commands. **Step 2:** parameters are applied as systemd unit environment
variables through Quadlet drop-ins (`<unit>.<suffix>.d/50-margot-parameters.conf`, `[Service]
Environment=`); `pointer` is defined as a unit environment variable name for quadlet, so unit files
use systemd expansion (`${NAME}`) in `Exec=`, `PublishPort=`, etc.; values come from descriptor
defaults and `--set`. **Step 3:** final checks: unit-name collisions across the Quadlet search path
(hard error), Quadlet-generator dry-run of the staged files, post-reload service verification.
No `--type`, no `--force`, no descriptor schema gate: simple but fully working. Compose and helm
profiles and `packageLocation` components are refused (see Backlog). Runs against the legacy
`margo.yaml` name; Sprint 14 sweeps it. Depends on Sprints 11 and 12. Full plan at
[`.kiro/sprints/sprint-13.md`](.kiro/sprints/sprint-13.md).

### Sprint 14 — `margot.yaml` project file and `margot migrate`

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
Sprints 11, 12 and 13 (`margot install` is swept in the rename). Full plan at
[`.kiro/sprints/sprint-14.md`](.kiro/sprints/sprint-14.md).

### Sprint 15 — Helm components: build and push

Helm is entirely absent today (no `PackageType.HELM`, `<helm_chart_tag>` hard-wired to `""`,
no `helm:` block). Adds a `helm:` block to the project file mirroring `compose` / `quadlet`
(variants, placeholder substitution and `image` search/replace on a temp copy — never Jinja2,
since Go templates use `{{ }}`), and `build -t helm` / `push -t helm` delegated to the host
`helm` binary through a thin wrapper (`infra/helm.py`, Helm >= 3.8, Helm 4 accepted; margot does
not reimplement helm). Helm is required only when a `helm:` block is declared. Helm decides
the pushed path from the chart's `Chart.yaml` name, so margot does not pre-validate it: it
compares helm's own `Pushed:` reference with the expected `repository:tag` after the push and
reports a mismatch. `describe` and `verify` also gain a first project-level check (helm component
`name` vs the project's `Chart.yaml` name). Also
ships a second container image that contains helm, and a CI job that tests Helm 3 and Helm 4.
Depends on Sprint 14 (project file rename). Full plan at
[`.kiro/sprints/sprint-15.md`](.kiro/sprints/sprint-15.md).

### Sprint 16 — Helm charts on the pull side

Detects Helm charts from the manifest's config/layer media types (they set no `artifactType`),
so `pull` stops refusing them, `pull --recursive` follows helm components instead of warning,
and `margot package` can bundle built helm archives. No `helm` binary needed. Images referenced
only inside a chart are not bundled (documented limitation). Depends on Sprint 15. Full plan at
[`.kiro/sprints/sprint-16.md`](.kiro/sprints/sprint-16.md).

### Sprint 17 — OS trust store and per-registry CA trust from `certs.d`

margot verifies registry certificates against the operating-system trust store (stdlib
`ssl` default context) instead of the bundled `certifi` file, and additionally reads the same
per-registry CA directories as Podman, Buildah and Skopeo (`containers-certs.d(5)`:
`~/.config/containers/certs.d`, `/etc/containers/certs.d`, and the other documented roots), so a
private registry that works with `podman pull` also works with margot's registry commands. Per
host, the `*.crt` files are added to the trust for that registry's connections only, through an
in-memory `SSLContext` on a small `requests` adapter (no temp bundle file, no `httpx` migration).
Automatic only: no flag, env var or setting. Client certificates are deferred (see Backlog).
Independent of Sprints 11–16. Full plan at [`.kiro/sprints/sprint-17.md`](.kiro/sprints/sprint-17.md).

---

## Backlog / Stack (Sprint 18+)

Unordered within groups; sequencing decided at sprint planning.

### Display UX

- Minified JSON output + make minified the **default** display for artifacts
  (`console.print_json` is still pretty-printed; fetch may keep pretty as default — TBD).
- Table output when listing **multiple** URIs (new `list`-style command).
- `--json` for the action commands `build`, `push`, `pull` and `install` (deferred from Sprint 10, which
  only covers `describe` and `verify`). Revisit once Sprint 10's pattern is proven.

### Manifest recognition in `fetch`

- `verify` / `describe` already validate and render Margo descriptors, locally and from an
  OCI URI (Sprints 6–9); what is missing is `fetch` *classifying* what it prints:
  recognised margo manifest / compose / quadlet component / unknown OCI artifact.

### More artifact types

- `pull` already detects margo, compose and quadlet via `artifactType`; `fetch` prints the
  raw manifest for anything. Helm chart detection is scheduled in Sprint 16. Remaining: detect
  plain image artifacts — extend `PackageType` (no `IMAGE` member today) with per-type handling
  and display.

### Cross-cutting

- `margot init` — scaffold a new Margo project: generate a starter `margot.yaml` and the
  expected directory layout (`margo/app.yaml.jinja`, optional `compose/` / `quadlet/`).
  The command does not exist yet. Sprint 14 reworks the "project file not found" error hint
  to point at `margot migrate`; once `init` lands, mention it there too.
- `margot migrate` — now scheduled as Sprint 14 (see Planned Sprints).
- `migrate` follow-up (low priority, owner prefers static `app.yaml`): partial reverse
  templating — only the few fields `margot.yaml` manages (`id`, `version`, component
  `repository`/`revision`, catalog), everything else verbatim. Acceptance: render the
  template with the generated `margot.yaml` and compare parsed YAML to the source.
- **chore:** remove the legacy `margo.yaml` read path at **1.0.0** (deprecated in Sprint 14);
  and rename the internal `MargoYaml` / `load_margo_yaml` identifiers to match `margot.yaml`.
- Scheduled in Sprint 14 (no longer backlog): `pull --recursive` component-name
  sanitisation (Item 1, may ship as an earlier patch) and per-variant `repository` (Item 3).

### Registry TLS follow-ups (after Sprint 17)

- **Client certificates (mTLS).** Honour `*.cert` / `*.key` pairs in `certs.d` (matched by file
  basename). Deferred from Sprint 17.
- **OS trust store on non-Linux.** Sprint 17 relies on the stdlib default context, which is
  enough on Linux. Revisit with `truststore` for macOS / Windows system stores if needed.
- **Registry transport.** Replace oras-py's `requests`-based HTTP layer (`provider.py`, `auth/*`)
  with `httpx`, either through a margot-owned OCI Distribution client or a fork. Large: manifests,
  chunked blob upload, token/basic/ECR auth, retry, Docker Hub quirks, Docker credential loading,
  and the tests that mock the HTTP layer. `requests` stays installed regardless (`docker`,
  `podman`, `linkml` need it), and httpx 0.28 still defaults to `certifi`, so this buys no trust-store
  benefit that Sprint 17 does not already deliver. Needs a spike and an owner decision (it
  revisits the oras-py choice recorded in `tech.md`) before any sprint.
- **Helm.** Pass the discovered CA to the host `helm` (`--ca-file`) once `infra/helm.py` exists
  (Sprint 15); Sprint 17's `infra/tls.py` is built to be reused for this.

### `margot install` follow-ups (after Sprint 13)

Known, accepted limitations of the first version — documented in `docs/commands/install.md`.

- **`packageLocation` / `keyLocation` components.** Spec-style compose components point at an
  HTTPS tar.gz instead of an OCI `repository`/`revision`. v1 refuses them (naming the component);
  assumed limitation, like helm. Needs: HTTPS-only download with safe extraction, an explicit
  stance on signature verification via `keyLocation`, and a decision on redirects/size limits.
- **Compose profiles (next install sprint).** Refused in Sprint 13 (quadlet first). Needs a
  payload location, `podman compose` / `docker compose` `up -d`, and parameters as environment
  variables (the spec's compose `pointer` meaning).
- **Helm profiles.** Refused today (no cluster on the host). Revisit with a clear target model
  (host `helm` against a user-selected kube context?) once Sprints 15–16 land.
- **Quadlet parameter follow-ups.** Sprint 13 Step 2 maps `pointer` to a systemd unit environment
  variable on all units of the component and takes `--set` values as plain strings. Remaining:
  validate `--set` against the descriptor schema (`dataType`, length, regex, range, options),
  per-unit targeting, array data types, a secret mechanism (values are clear text in the drop-in
  and visible through `systemctl show`), `immutable` enforcement on upgrade.
- **`margot uninstall`, `margot list` / `status`** on top of the ownership marker
  (`<application-id>/.margot-install.json`). Until then a profile switch for an installed
  application is refused and cleanup is manual.
- **Rollback** of a partially applied install (v1 reports what was applied and stops).
- **Install a bare compose/quadlet component by URI** (no application, no profile).
- **`--json` for `install`**: fold into the action-commands `--json` item under Display UX.
- **Runtime selection** (`--runtime`), if a host with both Podman and Docker needs a choice.

---

## Completed Sprints

| Sprint | Capability | Release |
| -------- | ----------- | --------- |
| Sprint 1 | `margot fetch` — anonymous OCI manifest retrieval, pretty-printed JSON output, URI validation, `margot --version` | [0.1.0](https://github.com/karnarokEpoch/margot/releases/tag/0.1.0) |
| Sprint 2 | `margot pull` — anonymous OCI artifact pull to disk, artifact type detection via `artifactType`, layer naming (title annotation → manifest-level fallback), `--force` override for unknown types, shared `domain/uri.py` | [0.2.0](https://github.com/karnarokEpoch/margot/releases/tag/0.2.0) |
| Sprint 3 | `margot build` — local artifact build for margo/compose/quadlet package types, placeholder substitution (`<app_tag>` from `appVersion`, `<margo_tag>`, `<compose_tag>`, `<quadlet_tag>`), variant support, idempotent output dir, multi-type `-t` flag, `margo.yaml` project descriptor, dynaconf config layering, pure-Python filesystem ops | [0.3.0](https://github.com/karnarokEpoch/margot/releases/tag/0.3.0) |
| Sprint 4 | `margot auth login` / `margot auth logout` + `margot push` — OCI registry authentication via oras-py (`margot auth` subcommand group), credential expiry tracking (`~/.config/margot/credentials.toml`), proactive expiry check before registry ops, push built artifacts (margo/compose/quadlet) with correct `artifactType`, media types, and OCI annotations, SemVer gate before push, multi-type + variant support mirroring build | [0.4.0](https://github.com/karnarokEpoch/margot/releases/tag/0.4.0) |
| Sprint 5 | `margot auth status` (credential expiry table), authenticated `fetch`/`pull` (transparent oras-py credential use), and the Jinja2 `app.yaml.jinja` rendering refactor: `id`/`version` required top-level fields, no `margo:` block (top-level `directory`/`repository` for the margo artifact instead), optional variant `version` with `<base>+<type>-<name>` derivation, `image: {search, replace}` block for compose/quadlet dev-local image swapping (`replace` is a Jinja2 template rendered with `StrictUndefined`), unresolved-placeholder warnings, per-component error messages. | [0.5.0](https://github.com/karnarokEpoch/margot/releases/tag/0.5.0) |
| Sprint 6 | `margot verify` — local-only LinkML validation of the Margo application description (`app.yaml`, or `app.yaml.jinja` rendered to a temp file, never requiring a prior `build`), upstream Margo spec schema vendored at draft commit `45f4359` with that commit reported in the output, curated recommended schema (`--recommend`) as a lint pass and `--strict` as a contract, `--only-recommend` to lint against the recommended schema alone, `--schema` / `--recommended-schema` overrides, `validation/` LinkML adapter layer (plugin set + finding formatter, `x-placeholder-extensions` stripped so vendor content never false-fails), Jinja2 rendering extracted to `infra/templating.py` and shared with `build`, standalone descriptor resolution reused by `describe`, plain CI-style pass/fail output | [0.6.0](https://github.com/karnarokEpoch/margot/releases/tag/0.6.0) |
| Sprint 7 | `margot describe` — read-only visual view of the Margo application description with rich panels and trees organizing the raw descriptor for human review. Identity+catalog panel with apiVersion title, deployment profiles with per-profile components and properties, and configuration-first join tree (section → setting → schema/parameter → pointer → components). Renders `type` verbatim (supports `quadlet` ahead of upstream spec), shows per-pointer component ratios against deduplicated component index, unreferenced-parameters subtree, scalar values in literal form (quoted strings, bare numbers, empty string as `""`, absent as `—`). No validation, no `linkml` import, exit 0 always except unloadable descriptor (exit 1). | [0.7.0](https://github.com/karnarokEpoch/margot/releases/tag/0.7.0) |
| Sprint 8 | `describe` component-first view (`--section component-first`, mirroring Sprint 7's section-first walk) and `--section config` renamed to `--section config-first` (no alias); read-only orphan/dead-end detection (`--section orphans`: unreferenced parameters, unresolved schema references, unused schemas, dangling component pointers); documented shell completion setup (`README.md`, `docs/index.md`). No validation exit paths added — stays inside `describe`'s existing read-only contract. | [0.8.0](https://github.com/karnarokEpoch/margot/releases/tag/0.8.0) |
| Sprint 9 | Remote OCI inspection for `describe` and `verify` (optional positional URI, shared fetch/pull path); `margot package` offline bundle command with OCI image inclusion (`--no-images`, `--runtime`, `--platform`); Docker Hub normalization (`docker.io` → `registry-1.docker.io`, `library/` prefix for official images); attestation manifest filtering for multi-arch indexes. | [0.9.0](https://github.com/karnarokEpoch/margot/releases/tag/0.9.0) |
| Sprint 10 | `--json` output for `describe` and `verify`, stable exit-code taxonomy, structured JSON error envelopes, and explicit `--no-color` / `NO_COLOR` controls; default Rich rendering preserved. | [0.10.0](https://github.com/karnarokEpoch/margot/releases/tag/0.10.0) |
