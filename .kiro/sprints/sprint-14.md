# Sprint 14 — Helm components: build and push

**Status:** draft — D2, D3 and D4 settled by the owner (2026-10-15); spikes S1, S2 and S3 resolved against Helm 4.2.0 + zot (2026-10-16); S4–S6 covered by the owner's "Helm 3.8–4.2 UI is stable" ruling
**Type:** feature
**Owner:** python-dev (docs: docs-writer)
**Release:** planned for `release/X.Y.Z` (TBD, after Sprint 13)

---

## 1. Goal

margot builds and pushes Helm charts that a project owns, the same way it already does
compose and quadlet components: a `helm:` block in the project file, variants, placeholder
substitution and `image` search/replace on a temp copy, `margot build -t helm`,
`margot push -t helm`. Packaging and pushing are delegated to the host `helm` binary
through a thin wrapper — margot does **not** reimplement helm. A second container image
that contains helm is published, CI exercises Helm 3 and Helm 4, `describe` and `verify` gain a
first project-level (non-manifest) consistency check, and margot gains a real `--plain-http`
capability for talking to local/insecure registries — needed to test the helm integration
honestly, and applied uniformly to the existing oras-py registry path as well.

---

## 2. Context

Helm is currently absent from the product:

- `PackageType` has no `HELM` member (`domain/models.py`).
- `<helm_chart_tag>` is a declared placeholder but `services/build.py::_build_placeholder_map`
  hard-wires it to `""`; it is also listed in `infra/filesystem.py::SUPPORTED_TAG_PLACEHOLDERS`.
- The project file parser (`domain/metadata.py::load_margo_yaml`) only knows `compose` and
  `quadlet`; `docs/examples/minimal.md` states margot "does not build the Helm chart itself".
- Helm components exist today only inside `app.yaml`, pointing at *external* charts (e.g. the
  bitnami example). That keeps working unchanged: the new `helm:` block is **opt-in**, for charts
  the project itself owns.
- There is no `subprocess` use anywhere in `src/margot` today — `infra/helm.py` introduces the
  first one (check the Ruff config for `S603`/`S607` before assuming they are quiet).
- `Containerfile` is `python:3.12.13-alpine3.24`; `release.yml` builds and pushes one image to
  GHCR; `ci.yml` has one `test` job (Python 3.12/3.13/3.14). `pyproject.toml` sets
  `--cov-fail-under=90` in pytest `addopts`, so any test subset run on its own must pass
  `--no-cov`.

**Decision record (owner, 2026-10-15): wrapper over the host `helm` binary.** Alternatives
evaluated and rejected:

- `helm-python-sdk` 0.2.2 (ctypes over a Go c-shared library, no binary needed). Capable
  (`package`, `push`, `dependency_update`, `lint`), but: Alpha, single maintainer, ~6 weeks old at
  evaluation; the native library is a prebuilt binary from a second repo by the same author;
  musl/Alpine unsupported (golang/go#54805, still open); and the Linux x86_64 wheel measured
  71.5 MiB / ~243 MiB installed because the 81 MiB library is stored three times (symlinks
  flattened). A real `helm` is 19.4 MiB (v4.3.0) / 17.8 MiB (v3.22.0) to download and ~63 / ~59 MiB
  unpacked, and is only needed by people who build or push helm components.
- Pure-Python packaging + oras-py push: reimplements `helm package`/`push`. Rejected by the owner.

Facts taken from the Helm docs (verified; the registries page has *not* been updated for Helm 4,
hence spike S6): `helm package` supports `--version`, `--app-version`, `--dependency-update`,
`--destination`; `helm push CHART REMOTE` requires `REMOTE` to be prefixed with `oci://` and to
**contain neither the basename nor the tag** — the basename is inferred from the chart's `name` and
the tag from its semantic version ("a strict requirement"); on success it prints
`Pushed: <registry>/<path>/<chart>:<tag>` and `Digest: sha256:…`; some registries require the
repository/namespace to exist beforehand, otherwise the push errors; OCI support is GA from Helm
3.8. The Margo spec says a helm component's `name` is used as the chart name and its
`repository`/`revision` locate the chart.

Dependencies:

- **Sprint 13** — project file is `margot.yaml` there, and `repository` becomes settable per
  variant. This sprint adds the `helm:` block to that file. If Sprint 13 slips, the block is added to
  `margo.yaml` and renamed with it.
- Sprint 10 (exit codes) is not a dependency; use `console.fatal` as it exists at implementation
  time.

---

## 3. Authoritative Design

### 3.1 Scope

**In scope:** `infra/helm.py` wrapper; `PackageType.HELM`; `helm:` block (parse, template
context, docs); `build` and `push` for helm (flat and variants); `<helm_chart_tag>` made real;
second container image; CI jobs; docs; the component-name check in `describe` (Item 6) and in
`verify` (Item 7); `--plain-http` global flag/env var/setting applied to both the oras-py and
helm registry paths (Item 8).

**Out of scope (non-goals):** `pull`/`fetch`/`package` handling of helm charts (Sprint 15);
provenance/signing (`--sign`); `helm lint` integration; discovering images inside charts
(`helm template`); values-overlay style variants; HTTP chart repositories (OCI only); Helm 2 and
Helm < 3.8; any Python helm library; project checks other than the helm component-name check;
`--insecure` / TLS-verification skipping (distinct from `--plain-http`, see §3.11).

### 3.2 Item 1 — `infra/helm.py` wrapper

- **Binary resolution:** a dynaconf setting (env `MARGOT_HELM_BIN`, matching the existing
  `MARGOT_` prefix) wins; otherwise `shutil.which("helm")`. Selective imports per
  `code-conventions.md`.
- **Lazy:** nothing in this module runs unless a helm step runs. A project without a `helm:` block
  never touches helm, including under `-t all`. A project *with* a `helm:` block and no usable
  binary is an **error**, never a silent skip.
- **Version gate:** run `helm version` once per process, parse the semantic version, require
  `>= 3.8.0`. Helm 4 accepted. Too old → actionable error naming the found version.
- **Execution:** argument list, `shell=False`, captured stdout/stderr, text mode, never
  `check=True`. Non-zero exit → `HelmError` (new exception in `infra/helm.py`, same pattern as
  `OciRegistryError`) carrying the trimmed stderr, with a short hint for the common cases
  (authentication failure; repository/namespace not created on the registry). `console.debug` the
  command line per call (`infra/` rule). **No secret is ever placed on the command line** (visible
  in `ps`).
- **Operations (names indicative):**
  - `package(chart_dir, version, app_version, destination, dependency_update)` → path of the
    produced `<chart>-<version>.tgz`. Packages into an empty temp directory and returns the file;
    the caller moves it.
  - `push(archive, remote, ...)` → runs `helm push <archive> <remote>` and returns the parsed
    `Pushed:` reference and digest (see §3.5).
  - `read_chart_name(chart_dir)` → `name` from `Chart.yaml` via PyYAML (no helm needed). Parsing
    logic in `domain/`, file read in `infra/`.
- **Inputs validated before use:** `remote` must start with `oci://` (so it can never be parsed as a
  flag); chart paths are absolute.

### 3.3 Item 2 — `helm:` block in the project file

Same shape as `compose` / `quadlet`:

| Field | Required | Default | Notes |
|---|---|---|---|
| `version` | Yes | — | Chart version base; OCI tag in flat mode; derivation base for variants. |
| `repository` | **Yes** | — | Where the chart is expected to live: `<parent>/<chart name>`. margot passes `<parent>` (last segment removed) to `helm push`; helm adds the chart name. Not compared with `Chart.yaml` before pushing (D2). No global fallback. |
| `directory` | No | `helm` | Flat: chart root (`Chart.yaml` here). Variants: `helm/<variant>/` is a full chart. |
| `variants` | No | — | Same semantics as compose/quadlet; version `<base>+helm-<name>` when omitted. |
| `image` | No | — | `{search, replace}`, same rules as compose/quadlet. |
| `dependencyUpdate` | No | `false` | Runs `helm package --dependency-update`. Needs network. |

- Component name defaults mirror the others: `{id}-helm` (flat), `{id}-helm-{variant}`.
- Expose helm in the Jinja2 context exactly like compose/quadlet so `app.yaml.jinja` can template
  `repository` / `revision` (mirror `_build_component_context`; read `docs/templating.md`).
- `PackageType.HELM` added; `-t helm` accepted by `build` and `push`; `-t all` includes helm only
  when the block is declared (same "not defined" skip pattern, but a declared block with a missing
  binary fails).

### 3.4 Item 3 — Build

1. Copy the chart directory (or variant directory) to a temp dir (`copy_tree`, honours
   `.rsyncignore`).
2. `substitute_placeholders` on the copy: `<app_tag>`, `<margo_tag>`, `<compose_tag>`,
   `<quadlet_tag>`, **`<helm_chart_tag>` (now the real chart version)**, plus the `image` pair.
   **Never Jinja2** — Go templates in `templates/` use `{{ }}`.
3. `helm package <copy> --version <real SemVer> --app-version <appVersion> -d <empty temp>`
   (`--dependency-update` when enabled). `--app-version` is omitted when `appVersion` is absent.
4. Move the archive to `.dist/<version-with-underscore>/`.
5. **Version trap (resolved by S1).** margot replaces `+` with `_` for directory names and
   `BuildTarget.version` (`services/build.py`). Helm must receive the **real SemVer with `+`** on
   `helm package --version`; helm itself converts `+` → `_` in the OCI tag on push and back to `+`
   on pull (S1, verified round-trip). No fallback to the underscore form is needed.
6. `Chart.yaml` missing → error before any helm call.

### 3.5 Item 4 — Push

**Helm is the source of truth for where a chart lands (owner decision D2).** margot does not
validate `repository` against `Chart.yaml` before pushing, and cannot ask helm to use a given name:
`helm push` infers the name and tag from the archive.

1. SemVer gate and the credential-expiry check run first (existing behaviour for registry calls).
2. Derive the remote: `repository` split at its last `/` → `oci://<parent>` (helm rejects a remote
   containing the basename or tag).
3. Run `helm push <archive> <remote>`. Parse the `Pushed: <ref>` line from stdout.
4. Compare `<ref>` with the expected reference `repository:tag` (tag with `+` → `_`). If they
   differ, fail with an error that states both, e.g. *expected `…/charts/web-frontend:1.0.0`, helm
   pushed `…/charts/nginx:1.0.0` (the chart name comes from `Chart.yaml`); the artifact is already
   in the registry and margot does not delete it.* If the `Pushed:` line cannot be parsed (format
   change in Helm 4), warn that the pushed reference could not be verified; do not fail.
5. **Credentials (S2, resolved):** point helm at margot's login via `--registry-config` /
   `HELM_REGISTRY_CONFIG` (docker-config format). Confirmed: helm authenticates from that file with
   no password on argv. Never `--password`.
6. Variants push each variant's archive to its `repository`; one `helm push` per archive.

### 3.6 Item 5 — Container image with helm, and CI

- **Second image** `Containerfile.helm`: same base as `Containerfile` plus a helm binary. Install
  the official release tarball for a version pinned by `ARG HELM_VERSION`, verifying its published
  checksum (alternative: `apk add helm`, available as 3.18.4 in Alpine v3.22 community; v3.24 not
  checked, and Helm 3 only). Official binaries are static Go, expected to run on musl — verify at
  build. Tags: `ghcr.io/<repo>:<version>-helm` and `:latest-helm`; the existing image is unchanged.
  `release.yml` `container` job builds and pushes both; check `release-check.yml` for image builds.
- **CI:** new `test-helm` job in `ci.yml`: matrix over one pinned Helm 3.x and one pinned Helm 4.x
  (latest patch at implementation time, bumped deliberately), Python 3.12 only. Installs helm by
  checksum-verified tarball download (preferred over a third-party action). Runs
  `make test PYTEST_ARGS="-m helm --no-cov"`. Register a `helm` pytest marker in `pyproject.toml`.
  Tests marked `helm` are skipped when `which("helm")` is `None`, so the existing `test` job and
  local runs without helm are unaffected. S3 is resolved: a zot (or `registry:2`) service container
  enables a real push test, using the real `--plain-http` flag/setting built in this sprint
  (Item 8, §3.11) — not a test-only workaround.
- The existing `test` job must keep ≥ 90 % coverage **without** helm: unit tests mock `which`/`run`.

### 3.7 Spikes — resolved (2026-10-16)

Run against **Helm v4.2.0** and a **zot v2.1.22** registry (htpasswd auth, plain HTTP on
`127.0.0.1:5000`), pushing the project's own `sensor-dashboard-1.2.3+helm-x` chart. **Owner
ruling (2026-10-16): the Helm 3.8–4.2 user interface is stable and differences are minor;
Helm 3 is not re-tested. S4/S6 are treated as answered by the Helm 4.2 run under this ruling.**

- **S1 — version `+` → OCI tag. RESOLVED.** `helm package --version 1.2.3+helm-x` is accepted
  (confirmed 2026-10-15) and produces `sensor-dashboard-1.2.3+helm-x.tgz`. On push, **helm itself
  converts `+` → `_`** and stores the tag `1.2.3_helm-x`; it prints the convention to stderr
  ("changing plus (+) to an underscore (_) … and back to a plus (+) when pulling"). Registry tag
  list confirmed `["1.2.3_helm-x"]`. **Round-trip verified:** `helm pull --version 1.2.3+helm-x`
  restores `sensor-dashboard-1.2.3+helm-x.tgz` with `version: 1.2.3+helm-x` in `Chart.yaml`.
  **Consequence:** margot passes the real SemVer (with `+`) to `helm package`; the §3.4 step-5
  fallback paths are dropped (see §3.4). The §3.5 post-push comparison must expect the `_` form,
  as it already states.
- **S2 — credentials without a password on argv. RESOLVED.**
  `helm registry login <reg> --username <u> --password-stdin --registry-config <file>` writes a
  standard docker-config (`{"auths":{"<reg>":{"auth":"…"}}}`) — the same format `margot auth login`
  produces. `helm push … --registry-config <file>` then authenticates **purely from that file**,
  with **no `--password` on the command line**. margot points helm at its own login via
  `--registry-config` (or `HELM_REGISTRY_CONFIG`). Requirement in §3.2/§3.5 satisfied.
- **S3 — plain-HTTP registry for integration tests. RESOLVED.** Against an HTTP registry, helm
  defaults to HTTPS and fails (`http: server gave HTTP response to HTTPS client`) unless
  **`--plain-http`** is passed; required on both `push` and `pull`. Login quirk: `helm registry
  login` against an HTTP registry prints the HTTPS error **but still writes a valid credential file
  and reports "Login Succeeded"** — harmless, not a failure.
  **Design decision (owner, 2026-10-16): `--plain-http` becomes a real, in-scope Sprint 14
  deliverable, not a follow-up.** Rationale (owner): without it there is no honest way to exercise
  the helm integration tests against a local, non-TLS registry — a throwaway test-only hack would
  be worse engineering than building the real flag once. Promoted to **Item 8** (§3.11): a global
  flag + `MARGOT_PLAIN_HTTP` env var + `settings.toml` field, applied **uniformly** to both the
  oras-py registry path (`push`/`pull`/`fetch`/`package`) and the helm path. Distinct from
  `--insecure` (TLS-verification skip), which stays out of scope — see §3.11 for the full design.
- **S4 — Helm 3 vs Helm 4 command differences. CLOSED by owner ruling.** Not tested on Helm 3; UI
  assumed stable across 3.8–4.2.
- **S5 — Alpine 3.24 `helm` availability.** Not tested here; informs the image choice only (§3.6).
  Default to the checksum-verified official tarball pinned by `ARG HELM_VERSION` unless the dev
  confirms a suitable `apk` package at build time.
- **S6 — `helm push` stdout format. RESOLVED for Helm 4.** On success, **stdout** carries two
  lines: `Pushed: <registry>/<path>/<chart>:<tag>` and `Digest: sha256:…`. The `+`→`_` convention
  notice goes to **stderr**. The parser keys on the `Pushed:` line (first token after the colon is
  the full reference). Behaviour when the chart name differs from the intended path segment is the
  D2 case: helm pushes under the **chart's own name**, so margot's post-push comparison (§3.5) is
  the mechanism that catches a mismatch.

### 3.8 Error cases

| Case | Behaviour |
|---|---|
| `helm:` declared, no binary | Error naming `MARGOT_HELM_BIN` and install hint; never skipped |
| helm < 3.8 | Error with the found version |
| No `Chart.yaml` in chart/variant dir | Error before any helm call |
| `repository` missing for helm | Error (no global fallback) |
| `helm` non-zero exit | `HelmError` with trimmed stderr and a hint for auth / missing repository |
| Pushed reference differs from `repository:tag` | Error stating expected vs actual; artifact stays in the registry |
| `Pushed:` line not parseable | Warning "could not verify pushed reference"; push counts as done |

### 3.9 Item 6 — Component-name consistency check in `describe` (first project-level check)

The Margo spec says a helm component's `name` is used as the chart name. `describe` flags when a
helm component declared in `app.yaml` does not match the chart the project itself builds.

- **Matching:** a helm component in the rendered descriptor corresponds to a `helm:` entry (flat, or
  one variant) when its `properties.repository` (scheme `oci://` stripped) and `properties.revision`
  equal that entry's `repository` and effective version (with `+` ≡ `_`, as `validate_semver`
  does). Components that match nothing (external charts, e.g. bitnami) are **skipped silently**.
- **Check:** the matched component's `name` must equal the `name` in that chart's `Chart.yaml`.
  Mismatch → one finding of severity **ERROR** naming the component, the chart directory and both names.
- **Preconditions:** needs the project file (so `describe` of a remote artifact or a bare
  `app.yaml` fallback — Sprint 12 — skips the check silently) and a readable `Chart.yaml`. No `helm`
  binary needed. A missing `Chart.yaml` for a matched entry is a finding too.
- **`describe` contract is unchanged:** read-only, exit code unaffected by findings (Sprints 7–8).
  Findings are rendered by `commands/describe.py` following `rich-rendering.md` (values as `Text`,
  no markup injection, ` · ` composition); one new section or a trailing panel, shown with the
  existing section selection.
- **Layering and "first stone":** a pure function in a new `domain/project_checks.py` takes the
  parsed descriptor and a mapping of chart dir → chart name and returns findings, reusing
  `Severity`/`ValidationFinding` from `domain/validation.py`. `services/describe.py` gathers the
  inputs (reads `Chart.yaml` through `infra/`). `verify` calls the same function (Item 7).
- **Shared helper:** the list of project helm charts to check (`directory`, `repository`, effective
  version, variant name) is computed by one pure function in `domain/` used by Item 6 and Item 7.
  `build` and `push` must use the **same** version derivation (`<base>+helm-<name>` for variants
  with no `version`); extract it from `services/build.py::_build_variant_component` rather than
  duplicating it, so the check cannot drift from what is actually built.

### 3.10 Item 7 — The same check in `verify`

`verify` reports the finding next to the schema results.

- **When it runs:** local project mode only, when a project file was resolved and at least one
  helm entry matches a helm component in the descriptor (same matching rules as Item 6). Not for
  `verify <uri>`, not for `--manifest`, not for the Sprint 12 bare-`app.yaml` fallback (all have no
  project file). **`--only-recommend` does run the project check** — project coherence checks are
  orthogonal to which schema flavor is active; `--only-recommend` means "Schema B only", not "skip
  everything else." No new flag.
- **Severity: ERROR (owner decision, 2026-10-15).** The check is project coherence: if it does not
  pass, something is wrong, so a finding **fails `verify` by default** — exit code 1, no flag
  needed, and `--strict` plays no part in it. `--strict` keeps its current meaning (Schema B only)
  and its help text and "has no effect" warning are unchanged.
- **Result shape:** `VerifyResult` gains `project_results: list[ValidationFinding]` (default empty,
  so existing constructors and tests keep working). `passed` becomes
  `no Schema A error and no project error and not (strict and Schema B findings)`. The check runs in
  `services/verify.py::verify`, on the descriptor that is already resolved or rendered there, while
  its temp file still exists.
- **Output — position: after the schema blocks, before the final `verify: PASS/FAIL` line.**
  One labelled block `Project checks`, always printed regardless of applicability: a
  `console.section("Project checks")` separator, then findings via `console.finding` (severity
  ERROR), then a `console.verdict` line. The verdict outcome is:
  - `PASS` (green) — check was applicable and clean.
  - `FAIL` (red, with count) — check was applicable and found errors.
  - `advisory` (orange3) — check was **not applicable** (no project file, remote URI, `--manifest`,
    bare `app.yaml` fallback, no matched helm components). Detail text states the reason, e.g.
    `skipped (no project file)`, `skipped (no matched helm components)`. This uses the existing
    `advisory` path in `console.verdict` — no new variant needed.
  The block must not exit early (`console.fatal` exits); same constraint as `_render_both_schemas`.
  Schema sections are still only shown when they have findings; the project block is **always**
  shown — even skipped — so the user always knows where they stand.

  **Example output — clean local project run:**
  ```
  ── Schema A (Margo spec) ───────────────────────────
  Schema A (Margo spec): PASS — no findings

  ── Schema B (recommended) ──────────────────────────
  Schema B (recommended): PASS — no findings

  ── Project checks ──────────────────────────────────
  Project checks: PASS — helm component sensor-dashboard matches Chart.yaml

  verify: PASS
  ```

  **Example output — mismatch found:**
  ```
  ── Schema A (Margo spec) ───────────────────────────
  Schema A (Margo spec): PASS — no findings

  ── Project checks ──────────────────────────────────
  ERROR  component "sensor-dashboard" · Chart.yaml name "my-chart" · expected "sensor-dashboard"
  Project checks: FAIL — 1 error

  verify: FAIL
  ```

  **Example output — remote URI (not applicable):**
  ```
  ── Schema A (Margo spec) ───────────────────────────
  Schema A (Margo spec): PASS — no findings

  ── Project checks ──────────────────────────────────
  Project checks: skipped (no project file)

  verify: PASS
  ```

- **A new kind of failure.** Until now `verify` failed only on the Margo spec schema, and
  `.kiro/steering/product.md` calls it "a schema-validation gate". With this item it also gates
  project coherence: update the `verify` docs and that sentence at close-out.
- **Sprint 10 coordination:** that sprint adds `--json` and exit codes to `verify`. `project_results`
  is additive; whichever sprint lands second adapts (serialise the new field; a project-check
  failure maps to the same validation-failure exit code as a Schema A error).

### 3.11 Item 8 — `--plain-http`: talk HTTP, not HTTPS, to a registry

**Promoted into scope (owner, 2026-10-16):** without this, Sprint 14's own helm integration tests
have no honest way to exercise a real push/pull against a local, non-TLS registry. Built once, as a
real capability, rather than as a throwaway test-only workaround.

- **Surfacing — three layers, one setting:**
  - A **global CLI flag** on the root callback, alongside `--verbose`/`--debug` in
    `commands/global_options.py`: `--plain-http` (boolean, default `False`).
  - A **`MARGOT_PLAIN_HTTP` env var**, following the existing `MARGOT_` prefix convention (see
    `MARGOT_HELM_BIN` in §3.2).
  - A **`settings.toml` field** (dynaconf), so it can be set once per machine/project rather than
    typed on every invocation — this is the owner's explicit motivating use case (a local zot
    without TLS).
  - Standard dynaconf layering applies: CLI flag > env var > `settings.local.toml` > `settings.toml`
    (same precedence order as every other layered setting in the project).
- **Naming, deliberately not `--insecure`:** `--insecure` conventionally means "skip TLS
  certificate verification" (still HTTPS, just unverified) — a different capability, with a
  different risk profile, and **not** what this flag does. `--plain-http` means "use HTTP, do not
  attempt TLS at all." margot does not introduce an `--insecure`/TLS-skip flag in this sprint; that
  stays a distinct, unaddressed capability if ever needed later.
- **Scope — applies uniformly to both registry paths:**
  - **oras-py path** (`push`/`pull`/`fetch`/`package`): oras-py's own `OrasClient.__init__` /
    `oras.provider.Registry.__init__` already accept `insecure: bool = False` as a constructor
    parameter, separate from `tls_verify` (verified against the installed oras-py: signature is
    `(hostname=None, insecure=False, tls_verify=True, auth_backend='token')`). margot's
    `infra/oci.py::OrasClient.__init__` gains a `plain_http: bool = False` parameter and passes it
    through as `super().__init__(insecure=plain_http, ...)`. This is additive — the signature stays
    a superset per `code-conventions.md`'s inheritance rule, and every existing call site keeps
    working with the default.
  - **helm path** (`infra/helm.py`): the resolved flag/setting value is passed through as helm's own
    `--plain-http` on every `helm package`/`push`/`pull`/`registry login` invocation that touches a
    registry.
  - **One resolved value, read once per command invocation** (not re-read per call), then threaded
    down through `services/` to both `infra/oci.py` and `infra/helm.py` — no layer re-derives it
    independently.
- **Not retroactively applied to unrelated commands beyond wiring:** this sprint wires the setting
  through margot's existing registry call sites; it does not add new registry-facing commands.
- **Tests:** unit tests for `infra/oci.py` (constructor passes `insecure=True` through when
  `plain_http=True`) and `infra/helm.py` (the flag appears in the built argv when set, absent when
  not); an integration test using the real flag end-to-end against the local zot/`registry:2`
  service container from Item 5's CI job — this *is* the mechanism that makes that job's push test
  honest, not a parallel test-only path.
- **Docs:** global options reference, `settings.toml` reference, a short "working with a local/
  insecure registry" note (likely alongside or near the existing auth/registry docs).

### 3.12 Error cases — Item 8 addendum

| Case | Behaviour |
|---|---|
| `--plain-http` set, registry is actually HTTPS-only | Whatever oras-py / helm itself report for a protocol mismatch — not specially caught or reworded by margot |
| `--plain-http` not set, registry is plain HTTP | Existing HTTPS-by-default failure from oras-py / helm (no change from today) |

---

## 4. Checkable Steps

- [x] Spikes S1–S6 resolved (S1/S2/S3/S6 verified on Helm 4.2 + zot 2026-10-16; S4/S5 closed by
  owner ruling); results written into §3.7. S3's follow-up design (`--plain-http`) promoted to
  Item 8 (§3.11), in scope for this sprint.
- [ ] `infra/helm.py` + unit tests (mocked `which`/`run`): resolution order, version gate, error
  mapping and hints, `Pushed:` parsing, no secret in argv.
- [ ] `PackageType.HELM`; `-t helm` in `build` and `push`; `-t all` behaviour.
- [ ] `helm:` block parsing, validation, template context, component-name defaults.
- [ ] Build: placeholders (real `<helm_chart_tag>`), `image` pair, `helm package`, move to `.dist/`,
  variants, the `+` / `_` handling.
- [ ] Push: remote derivation, `helm push`, post-push reference comparison, credentials per S2,
  variants.
- [ ] Item 6: `domain/project_checks.py` + shared helm-chart-target helper + tests (match / no match
  / mismatch / missing `Chart.yaml` / external chart skipped), `services/describe.py` wiring,
  `commands/describe.py` rendering, e2e test.
- [ ] Item 7: `VerifyResult.project_results`, `services/verify.py` wiring, `commands/verify.py`
  block + verdict; tests: not applicable (remote URI, `--manifest`, bare `app.yaml`) → advisory/
  skipped verdict printed, exit 0 unchanged; clean local run → PASS verdict; mismatch → ERROR
  finding and FAIL verdict and exit 1 (without `--strict`); missing `Chart.yaml` → ERROR; `--only-
  recommend` local run with matched helm components → project check runs (not skipped).
- [ ] Item 8: `--plain-http` global flag (`commands/global_options.py`), `MARGOT_PLAIN_HTTP` env var,
  `settings.toml` field; `infra/oci.py::OrasClient.__init__` gains `plain_http` → `insecure`
  passthrough (unit test); `infra/helm.py` threads it into every registry-touching helm invocation
  (unit test); one resolved value read once per invocation and threaded through `services/` to both
  `infra/oci.py` and `infra/helm.py`; docs (global options, `settings.toml` reference, local/
  insecure-registry note).
- [ ] Integration tests marked `helm` (real helm; skipped when absent); push/pull test against the
  local zot/`registry:2` service container uses the real `--plain-http` flag from Item 8.
- [ ] `Containerfile.helm`; `release.yml`; image smoke test (`helm version` inside).
- [ ] `ci.yml` `test-helm` job (Helm 3 + Helm 4); `helm` marker registered.
- [ ] Docs: project-file reference (`helm:`), command pages (`build`, `push`, `describe`, `verify`),
  templating page, examples (a project that owns a chart), requirements note ("helm needed only
  for helm components"), container image page; update `docs/examples/minimal.md` wording.
- [ ] `.kiro/steering/oci-media-types.md`: add the Helm media types (config
  `application/vnd.cncf.helm.config.v1+json`, layer
  `application/vnd.cncf.helm.chart.content.v1.tar+gzip`) for Sprint 15 — reference only.
- [ ] `make docs-check` passes.
- [ ] Each task committed as one or more conventional commits.

---

## 5. Definition of Done

- [ ] All checkable steps completed.
- [ ] `make check` passes without helm installed.
- [ ] `test-helm` CI job green on Helm 3 and Helm 4 (or the local equivalent run, results quoted).
- [ ] `--plain-http` verified end-to-end against a real local non-TLS registry (zot or
  `registry:2`), on both the helm push path and at least one oras-py path (e.g. `push`/`pull`).
- [ ] Both container images build; the helm one reports its helm version.
- [ ] Docs updated and `make docs-check` passes.
- [ ] No TODOs left (or deferred with `# TODO(kiro): ...` and a ROADMAP entry).
- [ ] Each task committed as one or more commits on the feature branch — no bulk commit.
- [ ] Handed back for review (Gate 2). The agent does not push, open PRs, or manage branches.

---

## 6. Close-out Note

```text
(filled in after merge)
```

---

## 7. Decisions

- **D2 — settled (owner, 2026-10-15): helm is the source of truth; no pre-push chart-name rule.**
  Because `helm push` cannot be given a name (it infers name and tag from the archive), a mismatch
  does not make helm fail. Error handling is therefore after the fact: margot compares helm's own
  `Pushed:` reference with the expected `repository:tag` and reports the difference (§3.5). Rejected
  alternatives: validating the last segment against `Chart.yaml` before pushing; making
  `repository` the parent path and appending the chart name.
- **D3 — settled (owner, 2026-10-15): the component-name check lives in `describe`** (Item 6), as the
  first project-level check beyond the manifest.
- **D4 — settled (owner, 2026-10-15/16): the check is also added to `verify`** (Item 7), with
  severity **ERROR**: project coherence must pass, so a finding fails `verify` by default.
  Output layout confirmed (owner, 2026-10-16): `Project checks` block is positioned **after the
  schema blocks, before the final `verify: PASS/FAIL` line**; **always printed** regardless of
  applicability — `PASS`/`FAIL` when the check ran, `advisory`/`skipped` (orange3, reusing the
  existing `console.verdict` advisory path) when it did not apply, with a short reason. **`--only-
  recommend` also runs the project check** — project coherence is orthogonal to which schema flavor
  is active. No new `console.verdict` variant is needed.
- **D5 — settled (owner, 2026-10-16): `--plain-http` is in scope for Sprint 14, not a follow-up**
  (Item 8, §3.11). Raised by the S3 spike (helm needs `--plain-http` against a non-TLS registry);
  initially proposed by the planner as a cross-cutting follow-up sprint/backlog item, rejected by
  the owner: without it, Sprint 14's own helm integration tests have no honest way to exercise a
  real push/pull against a local registry, and a throwaway test-only workaround would be worse
  engineering than the real flag. Scope: global flag + `MARGOT_PLAIN_HTTP` env var + `settings.toml`
  field, applied uniformly to the oras-py path and the helm path — not `--insecure` (TLS-skip),
  which is a different, still out-of-scope capability.

---

## References

- [sprint-workflow skill](../skills/sprint-workflow/SKILL.md)
- [ROADMAP.md](../../ROADMAP.md)
- [sprint-13.md](./sprint-13.md) — project file rename this sprint builds on.
- [sprint-15.md](./sprint-15.md) — pull side of helm charts.
- [code-conventions.md](../steering/code-conventions.md), [rich-rendering.md](../steering/rich-rendering.md),
  [structure.md](../steering/structure.md)
