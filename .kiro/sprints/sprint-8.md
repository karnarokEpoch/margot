# Sprint 8 — `describe` component-first view + orphan detection + remote support

**Goal:** Extend `margot describe`'s configuration display with a second traversal
direction, add read-only orphan/dead-end detection, let `describe` render a remote OCI
artifact's application description directly (`margot describe <uri>`), and document
shell completion setup. No changes to `verify`, no new validation exit paths —
everything here stays inside `describe`'s existing contract (exit 0 always, except an
unloadable descriptor).

**Prerequisite:** Sprint 7 merged. Reuses `domain/describe.py` dataclasses
(`Configuration`, `ConfigurationSection`, `Setting`, `Parameter`, `ParameterTarget`) and
the component index built in Sprint 7 for pointer ratios.

---

## Context

Sprint 7 shipped one traversal of the configuration block: **config-first** — section →
setting → schema/parameter → pointer → components. It answers "what can be configured,
and what validates it" — the order a reviewer thinks in when reading the spec top-down.

It does not answer the inverse question a reviewer asks when looking at a *component*:
"what parameters touch this component, and what setting/schema governs each one?" That
requires walking the same data backwards.

Sprint 7 also flagged, but deliberately deferred, "coherence observations" — parameters,
settings, or schemas that don't connect to anything. This sprint picks that up as orphan
detection.

---

## Scope

### Item 1 — Rename `config` section to `config-first`, add `component-first`

**Rename:** `--section config` → `--section config-first`. This is a breaking rename
(no deprecation alias) — `describe` is unreleased-stage tooling, not yet load-bearing for
external scripts. Update `canonical_order`, the default-render set, `_render_section`
dispatch, the docstring, `FEATURES.md`, and `ROADMAP.md`.

**Add:** `--section component-first` — same configuration data, walked from the other
end:

```text
component → parameter (via its pointer) → Setting: <name> → Schema: <name> <dataType> · <constraints>
```

**Display model (`domain/describe.py`):** new pure-transform function building a
component-indexed view from the existing `Configuration` dataclass — no new YAML
traversal, no new I/O. For each component in the component index:

1. Walk every `ConfigurationSection` → `Setting` → `Setting.parameter_resolved.targets[]`.
2. A target whose `components` includes this component is one edge: component →
   parameter name → (value/default) → owning setting → schema.
3. A component with no incoming targets at all renders with a dim `no parameters` line
   (same "faithful, not judgmental" rule Sprint 7 used for empty collections — see
   rich-rendering.md rule 4 on shallow trees).

Order components the same way the existing component index orders them (declaration
order across deployment profiles, deduplicated) — do not introduce a second ordering
rule.

**Rendering (`commands/describe.py`):** one tree per component, same panel container as
`config-first`, added as a new `elif` branch in `_render_section`. Follow rich-rendering
rule 4 — a schema's constraints ride on the setting's line, not their own level.

**Files:**
- `src/margot/domain/describe.py` — new dataclass(es) + builder function.
- `src/margot/commands/describe.py` — new tree builder + `_render_section` branch,
  `--section` help text, canonical order.
- `tests/unit/domain/test_describe.py` (or equivalent) — builder unit tests, no mocks.
- `tests/e2e/test_describe_cli.py` — extend the sensor-dashboard fixture assertions to
  cover `component-first`.
- `FEATURES.md`, `ROADMAP.md`.

### Item 2 — Orphan / dead-end detection

**Read-only for now** (locked decision) — this is a display concern, not a validation
gate. No exit code change, no `linkml` import, no new flag on `verify`. Surfaces inside
`describe`'s existing `extensions` section or a new dedicated section (open question
below).

**What counts as an orphan:**
- A `Parameter` with no `Setting` referencing it. (Already tracked today —
  `Configuration.unreferenced` — but only rendered inside `config-first`, not
  surfaced as its own concern.)
- A `Setting` whose `schema` reference does not resolve to any declared schema.
- A `Schema` declared but not referenced by any `Setting`.
- A `Parameter.targets[].components` entry naming a component that does not exist in the
  component index (dangling pointer — distinct from "unreferenced", this is a broken
  reference rather than an unused one).

**Open questions to settle before implementation:**
- Does this get its own `--section orphans` (consistent with the other sections,
  explicit opt-in like `extensions`), or does it fold into `config-first`/
  `component-first` as a trailing subtree the way `unreferenced` parameters already do?
  Leaning toward a dedicated section — orphans are a cross-cutting concern spanning both
  traversals, not naturally owned by either.
- Dangling component references: is this within scope for Sprint 8, or does it belong
  with `verify --remote`'s reachability work (Sprint 8 backlog item)? They're different
  questions — "does this pointer's target exist in the descriptor" vs. "does this OCI ref
  resolve" — but worth confirming they don't overlap in implementation.

**Files:**
- `src/margot/domain/describe.py` — orphan-collection builder(s), pure transform.
- `src/margot/commands/describe.py` — rendering.
- Unit + e2e tests, `FEATURES.md`.

### Item 4 — Remote descriptor support: `margot describe <uri>`

**Goal:** let `describe` render a `margo`-type OCI artifact's application description
directly from a registry, without a local project checkout. Today `describe` only reads
a local `app.yaml`/`app.yaml.jinja` resolved via `margo.yaml`; `fetch`/`pull` can already
reach a remote artifact but only show raw manifest JSON or write layers to disk — there
is no "pull it and describe it" path. This item closes that gap while reusing the entire
existing display pipeline unchanged (including the `config-first`/`component-first`
sections from Item 1).

**Context (verified against source):**

- `commands/describe.py::describe_cmd` takes only `--project-dir` / `--manifest` /
  `--section` — no positional argument, no remote path at all.
- `services/describe.py::load_descriptor` resolves and loads a **local** descriptor via
  `services/verify.py::resolve_descriptor` (margo.yaml → app.yaml/.jinja → temp file if
  templated) and enforces the Item 1 (Sprint 7) load gate (must parse to a mapping,
  `kind == ApplicationDescription`).
- `services/pull.py::pull_artifact` already has the primitives needed for remote
  retrieval: URI validation (`domain/uri.py`), credential expiry check
  (`infra/credentials.py::check_credentials`), manifest fetch
  (`infra/oci.py::OrasClient.get_manifest`), artifact type detection
  (`domain/models.py::artifact_type_to_package_type`), and single-blob download
  (`OrasClient.download_blob`).
- `domain/layers.py::select_payload_layer` finds a manifest layer by `mediaType` — used
  today for compose/quadlet payload layers; the same helper works for the margo
  artifact's `app.yaml` layer (media type
  `application/vnd.margo.app.description.v1+yaml`, per `FEATURES.md`'s margo package
  media type table).
- `fetch`/`pull` deliberately skip SemVer validation on the tag (`FEATURES.md`: "No
  SemVer validation: `pull`/`fetch` retrieve/inspect arbitrary existing artifacts") —
  remote `describe` follows the same rule; it is an inspection command, not a build
  target.
- Only `margo`-type artifacts (`artifactType ==
  "application/vnd.margo.app.v1+json"`) carry an `app.yaml` layer at all — `compose` and
  `quadlet` artifacts are tarballs with no application description inside. Remote
  `describe` is scoped to margo artifacts only; anything else is a clear, immediate
  error, not a best-effort attempt.
- Domain display builders (`domain/describe.py`: `build_identity`, `build_catalog`,
  `build_deployment_profiles`, `build_configuration`, `component_index`, plus this
  sprint's new `component-first` builder from Item 1) and all rendering functions in
  `commands/describe.py` take a plain `dict` — they have zero knowledge of where that
  dict came from. No changes needed to either module's rendering logic.

**Sub-item 4a — Remote descriptor retrieval**

New function in `services/describe.py`: `load_descriptor_remote(uri: str) -> dict`.
Mirrors `load_descriptor`'s contract (same return shape, same load-gate errors) but
sources the YAML from a registry instead of disk.

Steps:

1. `domain.uri.validate_uri(uri)` — malformed URI fails immediately, before any network
   call.
2. `credentials.check_credentials(extract_hostname(uri))` — proactive expiry check,
   same as `pull`/`fetch`.
3. `OrasClient(hostname=...).get_manifest(uri)` — fetch the manifest.
4. Detect artifact type via `artifact_type_to_package_type(manifest.get("artifactType"))`.
   If not `PackageType.MARGO`: raise `ValueError` —
   `"Cannot describe artifact type '<type or none>': only margo artifacts
   (application/vnd.margo.app.v1+json) contain an application description. Use 'margot
   fetch <uri>' to inspect the raw manifest."`
5. `select_payload_layer(manifest.get("layers") or [], MARGO_DESCRIPTOR_MEDIA_TYPE)`
   where `MARGO_DESCRIPTOR_MEDIA_TYPE =
   "application/vnd.margo.app.description.v1+yaml"` (new constant — add alongside the
   existing `COMPOSE_LAYER_MEDIA_TYPE` / `QUADLET_LAYER_MEDIA_TYPE` constants in
   `domain/layers.py` for consistency). If no matching layer: raise `ValueError` —
   `"No application description layer found in this artifact."`
6. Download that single blob to a temp file via `OrasClient.download_blob` — use
   `tempfile` directly (or add a small helper in `infra/filesystem.py` if that better
   matches existing conventions there; dev agent's call).
7. Load + Item 1 gate: identical logic to `load_descriptor` (parse mapping, check
   `kind == ApplicationDescription`) — factor the shared gate logic out of
   `load_descriptor` into a small private helper (e.g. `_load_gate(path: str,
   source_label: str) -> dict`) so local and remote paths can't drift apart. Both raise
   the same `ValueError`/`TypeError` types the command layer already catches.
8. Always delete the temp file in a `finally`, matching the existing pattern in
   `load_descriptor`.

**Files:** `src/margot/services/describe.py`, `src/margot/domain/layers.py`,
`src/margot/infra/filesystem.py` (only if a helper is added).

**Sub-item 4b — CLI surface**

`commands/describe.py::describe_cmd` gains an optional positional `uri` argument:

```
margot describe [URI] [--project-dir PATH] [--manifest PATH] [--section ...]
```

- `uri: str | None = Argument(None, help="OCI reference to describe remotely, e.g.
  public.ecr.aws/g2n4p2m7/margo:1.0.0. Omit to describe the local project.")` — Typer
  `Argument`, not `Option`, matching `pull`/`fetch`'s existing positional-URI shape.
- Guard, checked before any I/O (same "reject before any I/O" pattern as `verify`'s
  `--recommend`/`--only-recommend` mutual exclusion): if `uri` is given **and**
  (`--project-dir` was explicitly passed with a non-default value **or** `--manifest` is
  set), fail fast with `console.fatal("URI and --project-dir/--manifest are mutually
  exclusive — describe either a remote artifact or a local project, not both.")`.
  - Note: `--project-dir` defaults to `"."` — the guard must distinguish "user passed
    `--project-dir .`" from "user didn't pass it," or it will false-positive on every
    remote call. Recommended approach: default `project_dir` to `None` in the
    signature instead of `"."`, and substitute `"."` only in the local branch. Confirm
    this doesn't break existing local-mode callers/tests that rely on the `"."` default
    being visible in `--help`.
- Branch: `uri` given → `describe_service.load_descriptor_remote(uri)`; else → existing
  `describe_service.load_descriptor(project_dir or ".", manifest)` call, unchanged.
- `--section` behavior is **unchanged and fully available** in remote mode, including
  Item 1's `config-first`/`component-first` — same canonical ordering, same
  default-set-minus-absent-extensions logic. The display model doesn't know or care
  where the dict came from, so there is no reason to restrict it.

**Panel subtitle for remote mode:** `build_identity_catalog_panel`'s subtitle currently
shows the resolved local path, suffixed `(rendered)` for `.jinja` sources. For remote
mode it should show the URI, suffixed `(remote)` — e.g. `public.ecr.aws/g2n4p2m7/margo:
1.0.0 (remote)`. Requires threading a `subtitle` string (or a small
`source_label`/`is_remote` pair) from `describe_cmd` into
`build_identity_catalog_panel` instead of always calling
`describe_service.resolve_descriptor` (which is local-only and must **not** be called at
all in remote mode — it has no meaning there and would force a spurious local
`margo.yaml` resolution).

**Files:** `src/margot/commands/describe.py`.

**Sub-item 4c — Error handling**

| Condition | Error | Exit |
|---|---|---|
| Malformed URI | `domain.uri.validate_uri`'s existing `ValueError` message | 1 |
| Non-margo artifact type | New clear message (step 4 above) pointing at `margot fetch` | 1 |
| Margo artifact, no `app.yaml` layer | New clear message (step 5 above) | 1 |
| Credentials expired | Existing `CredentialsExpiredError`, unchanged | 1 |
| URI + `--project-dir`/`--manifest` both given | New mutual-exclusion message | 1 |
| Downloaded YAML fails Item 1 load gate | Same message as today's local failure, pointing at `margot verify` — note: `verify` has no remote mode (out of scope), so the hint is slightly imprecise for remote callers but kept for consistency | 1 |

All via the existing `console.fatal(...)` call already used in `describe_cmd` — no new
exit-code taxonomy here (that's Sprint 9's concern, orthogonal).

**Decisions locked (not re-opened during implementation):**

1. Positional `Argument`, not an `--uri` option — matches `pull`/`fetch` precedent.
2. Margo-artifact-type gate is a hard error, not a warning or best-effort fallback.
3. `--section` is fully available in remote mode, same defaults and ordering as local.
4. Single-blob download (just `app.yaml`), not a full `pull_artifact` call — `describe`
   never needs icon/license/release-notes on disk.
5. No `--output`/persistence flag — this is inspect-only, same posture as `fetch`.
6. No SemVer validation on the remote tag — matches `fetch`/`pull`'s existing "arbitrary
   existing artifact" posture.

**Open question for the dev agent to resolve during implementation (not a blocker):**
exact mechanism for the mutual-exclusion guard's "was `--project-dir` explicitly passed"
check — changing its default from `"."` to `None` is the recommended approach; verify it
doesn't regress the `--help` text or any existing test asserting the literal default
value before finalizing.

**Tests:** per `AGENTS.md`/`code-conventions.md` — TDD, `domain/` first (no mocks), mock
`OrasClient` at the `infra/oci.py` boundary for service tests, Typer `CliRunner` for E2E.

- `domain/layers.py`: unit test for `MARGO_DESCRIPTOR_MEDIA_TYPE` and that
  `select_payload_layer` finds it.
- `services/describe.py`:
  - `load_descriptor_remote` happy path — mock `get_manifest` to return a margo-artifact
    manifest with an `app.yaml` layer, mock `download_blob` to write a valid descriptor
    fixture, assert the returned dict and that the temp file is deleted.
  - Non-margo artifact type → `ValueError` with the expected message.
  - Margo artifact, no matching layer → `ValueError`.
  - Load-gate failures (bad YAML, wrong `kind`) reachable via the remote path too —
    confirms the factored-out shared helper is actually shared.
  - Credentials-expired path delegates correctly.
- `commands/describe.py` (Typer `CliRunner`):
  - `margot describe <uri>` happy path renders the identical panels a local run
    produces for the same descriptor content.
  - `margot describe <uri> --project-dir foo` → mutual-exclusion error, no network call
    attempted.
  - `margot describe <uri> --section metadata` and `--section component-first` → only
    the requested panel renders, remote mode.
  - Subtitle shows the URI + `(remote)` marker.

**Documentation:**
- `FEATURES.md`: update the `margot describe` section — add the `<uri>` positional
  argument, the margo-only remote gate, the mutual-exclusion rule, and the `(remote)`
  subtitle behavior.
- `README.md`: optionally add a one-line example under "Inspect it visually" —
  `margot describe public.ecr.aws/g2n4p2m7/margo:1.0.0`.
- Run `make docs-check` if any `docs/` file is touched.

### Item 5 — Document shell completion setup

`--install-completion` / `--show-completion` are Typer-provided today (visible in
`margot --help`) but have no dedicated how-to anywhere — they only appear verbatim inside
the copied help-text block in `README.md`.

**Confirmed via `margot --show-completion bash`:** neither flag takes a custom output
path. `--install-completion [bash|zsh|fish|powershell|pwsh]` appends directly to the
shell's default rc file (e.g. `~/.bashrc`) — no `--path` option, not appropriate for
anyone managing their own sourced-completions layout (e.g. a file under
`~/.bash_profile`-managed includes rather than a raw rc append).

Add a short "Shell completion" subsection (README and `docs/index.md`, kept in sync per
existing convention) documenting **both** paths, not just the one-liner:

```bash
# Quick setup — appends to your shell's rc file directly
margot --install-completion

# Manual setup — prints the script; redirect it wherever you source completions from
margot --show-completion bash > ~/.local/share/bash-completion/completions/margot
```

Note the shell-restart requirement for both, and that `--install-completion` offers no
control over *where* it writes — call this out explicitly so users who curate their own
rc includes reach for `--show-completion` first.

**Files:** `README.md`, `docs/index.md`.

---

## Out of scope (explicitly deferred)

- Minified JSON default output, `list`-style command, manifest recognition on `fetch`,
  more artifact types in `fetch`, `verify --remote` — all still backlog, untouched by
  this sprint. See `ROADMAP.md` Backlog / Stack.
- Turning orphan detection into a `verify` gate (exit 1 on findings) — explicitly
  deferred until read-only output has been reviewed.
- Deprecation alias for `--section config` — dropped outright, not aliased.
- `--json` on remote `describe` — Sprint 9 lands `--json` independently; once it ships,
  remote mode gets it automatically since both paths converge on the same `dict` →
  display-dataclass pipeline. No `--json`-specific work needed in this sprint.
- compose/quadlet remote description — these artifacts have no `app.yaml` layer;
  attempting to describe one is a hard error (Item 4c), not a partial/best-effort
  render.
- Writing the pulled remote descriptor to disk — inspect-only, same posture as `fetch`.
  Use `margot pull` if the artifact needs to land on disk.
