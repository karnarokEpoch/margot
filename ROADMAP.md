# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

---

## Sprint 4 — `margot login` / `logout` + `margot push`

### Goal / Definition of Done

```
margot auth login --ecr --region us-east-1
margot push --type all
margot push --type margo
margot push --type compose --variant simple
margot auth logout
```

Authenticate with an OCI registry, then push built artifacts from `build_dir` to the
registry using oras-py. **Requires a prior `margot build` run** — push reads artifacts
from `build_dir`, it does not re-build. SemVer-gated: push rejects invalid tags before
any network call. Green unit + integration + E2E tests.

### Design decisions (locked)

- **Auth first, push second.** `auth login` / `auth logout` must work before push can be tested
  end-to-end. Both ship in this sprint.
- **CLI structure: `margot auth` subcommand group.** All credential-related commands
  live under `margot auth`: `margot auth login`, `margot auth logout`,
  `margot auth status`. This replaces the earlier flat `margot login` / `margot logout`
  design. Clean taxonomy, low nesting cost, and `auth status` fits naturally as a
  read-only sibling.
- **`margot auth login` signature:**
  `margot auth login [--registry REG] [--username USER] [--password-stdin] [--save-expiry]`
  Delegates entirely to `OrasClient.login(username, password, hostname)`. oras-py handles
  the full OCI auth challenge-response including ECR — no registry-specific code needed
  in margot. For ECR: caller passes `--username AWS` and the token from
  `aws ecr get-login-password` as the password; oras-py's `EcrAuth` backend takes it
  from there. No boto3 dependency in margot.
- **`margot auth logout` signature:**
  `margot auth logout [--registry REG]`
  Calls `OrasClient.logout(...)` and removes the expiry entry from credentials file.
- **Credential expiry check before every registry operation.** Implemented in
  `infra/credentials.py` as `check_credentials(registry)`. If `expires_at` is tracked and
  `now >= expires_at - 5min`, warn (or hard-fail if already expired) with a
  `margot login` hint. This runs before every push/pull/fetch call. See FEATURES.md for
  the full design.
- **`margot push` signature:**
  `margot push [--type margo|compose|quadlet|all] [--registry REG] [--repository REPO] [--build-dir DIR] [--variant VARIANT]`
  Mirrors `build` flags. No `--version` flag: version is read from the built artifact
  directory structure in `build_dir` (derived from `margo.yaml`).
- **SemVer gate on push.** Validate the tag before any network call. Same
  `validate_oci_tag` + `validate_semver` from `domain/tags.py`. Fail fast.
- **oras-py only.** No subprocess calls to ORAS CLI binary. All push via
  `OrasClient.push(...)`. See FEATURES.md for exact `files`, `manifest_config`, and
  `manifest_annotations` per type.
- **`artifactType` in manifest config, never in the tag.** margo → `application/vnd.margo.app.v1+json`,
  compose → `application/vnd.org.margo.component.compose+json`,
  quadlet → `application/vnd.org.margo.component.quadlet+json`.
- **Media types per layer.** See FEATURES.md push section for the exact per-file media
  type table (margo: `app.yaml`, `icon.png`, `license.txt`, etc.; compose/quadlet: `.tgz`).
- **OCI annotations.** Push includes `org.opencontainers.image.title`, `.description`,
  `org.margo.component.type`, `org.margo.component.version` as defined in FEATURES.md.
- **Multi-type push mirrors build.** `-t margo -t quadlet` pushes both; `--type all`
  pushes all defined components; missing components are skipped (same pattern as build).
- **`infra/credentials.py`** owns credentials file R/W. **`infra/ecr.py`** owns boto3
  token fetch. **`services/auth.py`** orchestrates login/logout flow. **`services/push.py`**
  orchestrates the push flow (credential check → tag validation → oras push).

### Tasks (thin vertical slice)

| # | Task | Layer | Notes |
|---|------|-------|-------|
| 1 | Credentials file R/W + expiry check | `infra/credentials.py` | `~/.config/margot/credentials.toml`. `check_credentials(registry)` warns/fails near/past expiry. |
| 2 | oras-py login/logout wrappers | `infra/oci.py` | Extend existing OCI infra with `login(...)` and `logout(...)`. |
| 3 | Auth service (login/logout orchestration) | `services/auth.py` | Call oras-py login/logout + optional expiry persistence. No registry-specific logic. |
| 4 | `auth login` + `auth logout` Typer commands | `commands/auth.py` | `margot auth` group with `login` and `logout` subcommands. Register in `main.py`. |
| 5 | oras-py push wrappers | `infra/oci.py` | `push_margo(...)`, `push_compose(...)`, `push_quadlet(...)` with correct media types and annotations. |
| 6 | Push service | `services/push.py` | credential check → tag validation → locate built artifact in `build_dir` → oras push. Mirrors build's type/variant loop. |
| 7 | `push` Typer command | `commands/push.py` | Flags mirror build. Calls push service. Register in `main.py`. |
| 8 | Tests: unit (credentials expiry logic), integration (mock OrasClient, assert push params + media types), E2E via CliRunner | `tests/` | Mock `OrasClient` at `infra/oci.py` boundary — never hit a live registry. |
| 9 | Update FEATURES.md `push`, `login`, `logout` sections as behaviour lands | `FEATURES.md` | |

### Out of scope (explicit → Sprint 5+)

`verify` (LinkML), display UX improvements, authenticated `fetch`/`pull` (anonymous
still works), manifest recognition & validation.

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

**Open question — templating engine:** the right approach is not obvious and should be a
design spike at the start of the sprint:
- **Plain string replace (extended):** simple, already in place, sufficient if structural
  generation is handled by a separate merge step. Cannot handle loops or conditionals.
- **Jinja2:** mature Python templating, handles loops/conditionals/filters, already used
  in many Python toolchains. Risk: YAML + Jinja indentation is error-prone; developers
  must learn Jinja syntax in their `app.yaml`.
- **Hybrid — generation + merge:** margot generates the structural scaffold from
  `margo.yaml` declarations and deep-merges it with the developer's `app.yaml` (which
  only contains the variable parts). Plain string replace (or Jinja2) applies only to the
  developer-authored portion. Cleanest separation of concerns but requires a defined
  merge strategy and schema for what margot auto-generates.
- **Helm-style Go templates reimplemented in Python:** effectively reinventing Jinja2
  with worse ergonomics. Not recommended.

**Decision needed at sprint planning** before any implementation begins.

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
|--------|-----------|---------|
| Sprint 1 | `margot fetch` — anonymous OCI manifest retrieval, pretty-printed JSON output, URI validation, `margot --version` | [0.1.0](https://github.com/karnarokEpoch/margot/releases/tag/0.1.0) |
| Sprint 2 | `margot pull` — anonymous OCI artifact pull to disk, artifact type detection via `artifactType`, layer naming (title annotation → manifest-level fallback), `--force` override for unknown types, shared `domain/uri.py` | — |
| Sprint 3 | `margot build` — local artifact build for margo/compose/quadlet package types, placeholder substitution (`<app_tag>` from `appVersion`, `<margo_tag>`, `<compose_tag>`, `<quadlet_tag>`), variant support, idempotent output dir, multi-type `-t` flag, `margo.yaml` project descriptor, dynaconf config layering, pure-Python filesystem ops | — |
