# Sprint 9 — Remote OCI resolution + offline bundle packaging

**Goal:** Five independent items shipping in the same sprint/release, each on its own branch/worktree per
`agent-workspace`:

- **Item 1 — Shared remote OCI resolution for `describe` and `verify`.** Let `margot describe` and `margot verify`
  inspect a published Margo application artifact directly, using the same OCI inspection and layer-pull mechanics as
  `fetch` and `pull`. A command with no positional URI remains local-project behavior; a command with a URI validates,
  pulls the remote margo artifact into a temporary directory, and then runs the existing local descriptor pipeline
  against that downloaded `app.yaml`. This finishes the remote `describe` capability that was planned in Sprint 8 but
  did not land in release 0.8.0, and extends the same capability to `verify`. It replaces the previous backlog concept
  of `verify --remote` reachability-only checks with actual remote descriptor validation.
- **Item 2 — `margot package`: offline bundle artifacts.** A new command that bundles already-`build`-produced margo,
  compose, and quadlet outputs from `.dist/<version>/` into a single self-contained `.tgz`, for deployment into
  disconnected/offline environments without registry access. New `PackageType.BUNDLE`. Never pushed — no OCI
  `artifactType`, no registry transport.
- **Item 3 — Container image inclusion in offline bundles, on by default.** Extends `margot package` (Item 2) to pull
  the container images referenced by bundled compose/quadlet content and embed them as OCI image-layout tars, by
  default — so a plain `margot package` is fully self-contained for `podman load` with no registry access at deploy
  time. This makes default `package` network-dependent for the first time; `--no-images` opts back out to Item 2's
  pure-local behavior. Built on Item 2's command; depends on it existing first.
- **Item 4 — Local container-daemon lookup for bundled images.** Adds a `--runtime podman|docker|none` flag (default:
  silent auto-probe Podman → Docker → registry) so an image already present in a local container daemon is used
  instead of pulled from the registry — covering locally built/tagged images that haven't been pushed yet. New
  optional `podman`/`docker` SDK dependencies; Docker-sourced saves are normalized into the same OCI image-layout
  shape Item 3 already uses. Depends on Item 3; independent of and parallel to Item 5.
- **Item 5 — Multi-platform filtering for bundled images.** Adds a repeatable `--platform <os>/<arch>` flag to narrow
  which platform(s) of a multi-arch image index Item 3's registry path pulls and saves. Default stays "every platform
  present," unchanged from Item 3. Depends on Item 3; independent of and parallel to Item 4.

**Prerequisite (Item 1 only):** Sprint 8's local `describe` views are released. The former Sprint 9 machine-output/
error-code plan has been renumbered to Sprint 10.

______________________________________________________________________

## Item 1 — Shared remote OCI resolution for `describe` and `verify`

### Context: current state (verified against source)

- `describe` and `verify` currently resolve only local files: an explicit `--manifest`, or `margo.yaml` in
  `--project-dir` followed by `app.yaml.jinja` / `app.yaml` resolution. Neither command accepts a positional URI.
- `services/verify.py::resolve_descriptor` is the shared local resolution mechanism. An explicit static `app.yaml`
  bypasses `margo.yaml`, which makes it suitable for a downloaded remote descriptor; `describe` layers its YAML-mapping
  and `kind: ApplicationDescription` load gate on top of this resolver.
- `services/fetch.py::fetch_manifest` already normalizes an optional `oci://` scheme, validates the OCI reference,
  checks credential expiry, and obtains a manifest through `infra/oci.py::OrasClient`.
- `services/pull.py::pull_artifact` performs the same registry checks and downloads artifact layers. Margo artifacts use
  the ORAS pull path and write their layers, including `app.yaml`, to the caller-provided output directory.
- `pull_artifact` currently adds a SemVer gate that conflicts with the documented behavior: `pull` and
  `fetch` are inspection commands and must retrieve arbitrary existing OCI references, including legacy tags. This
  defect would reject remote inspection references such as `public.ecr.aws/g2n4p2m7/margo:1.1.0_legacy-manifest`.
- `artifact_type_to_package_type` maps the OCI manifest's `artifactType` to `PackageType`. Only `PackageType.MARGO`
  contains an application description; compose, quadlet, and unknown artifacts must fail before their layers are
  accepted by `describe` or `verify`.

______________________________________________________________________

### Scope

#### Optional remote OCI URI for `describe` and `verify`

Both commands receive the same optional positional argument:

- `margot describe [URI] [--project-dir PATH] [--manifest PATH] [--section ...]`
- `margot verify [URI]` with its existing project, manifest, schema, recommendation,
  and strictness options

`URI` is a full tagged OCI reference, for example `public.ecr.aws/g2n4p2m7/margo:1.0.0`. An `oci://`-prefixed reference
remains accepted, matching `fetch` and `pull`.

#### Invocation contract

1. **No URI:** behavior remains exactly local. Existing `--project-dir`, `--manifest`, descriptor rendering, schema
   options, output, and exit behavior must not regress.
1. **URI supplied:** it is remote mode. It is never interpreted as a local filename or project path. A malformed/non-OCI
   value fails via the existing URI validation before any registry or filesystem operation.
1. **Mutual exclusion:** a URI cannot be combined with an explicitly supplied `--project-dir` or with `--manifest`. Fail
   before I/O with one shared clear message:
   > URI and --project-dir/--manifest are mutually exclusive — describe or verify either a
   > remote artifact or a local project, not both.

   Change the CLI's `project_dir` default to `None` and substitute `.` only for local
   mode, so the implementation can distinguish an omitted flag from `--project-dir .`.
1. All existing `verify` flags remain usable in remote mode. In particular, `--recommend`, `--only-recommend`,
   `--strict`, `--schema`, and `--recommended-schema` retain exactly their local semantics and mutual-exclusion checks.
1. All existing `describe --section` choices remain usable in remote mode. Section selection and canonical ordering do
   not vary by descriptor source.

#### Shared remote-resolution service

Add one service-level remote resolver (for example `services/remote.py`) used by both commands. It owns the entire
remote source lifecycle and returns a context containing:

the normalized URI, the path of the downloaded `app.yaml`, and a live temporary-directory handle whose cleanup remains
the caller's responsibility. The resolver must not produce rich renderables or validation output.

It must use the **same registry mechanics as `fetch` and `pull`**, not make a bespoke ORAS request or download only a
single blob:

1. Normalize `oci://`, validate the URI, and check credentials using the shared pull / fetch path.
1. Fetch the manifest through the shared OCI inspection path and map its `artifactType`.
1. Require `PackageType.MARGO` before downloading. For compose, quadlet, unknown, or absent artifact types, raise a
   clear error naming the actual type (or `unknown`) and direct the user to `margot fetch <uri>` for raw-manifest
   inspection.
1. Pull the margo artifact into a `tempfile.TemporaryDirectory`, with `recursive=False`. Reuse the margo layer-pull
   implementation behind `pull_artifact`; refactor common fetch/pull internals as necessary to avoid diverging URI
   validation, credential checks, manifest handling, or ORAS transfer behavior. Do not duplicate the margo layer
   downloader in the new resolver.
1. Locate the pulled root `app.yaml` from the pull result. If the artifact passed its type gate but did not produce an
   application description layer, raise a clear error.
1. Do not persist anything in the caller's directory. Always clean the entire temporary directory in `finally`, after
   the command has rendered or validated the descriptor.

The reusable boundary matters: an OCI retrieval defect seen through remote `describe` or `verify` must reproduce through
`margot pull` and be fixed in the shared pull/fetch mechanics, not papered over in either inspection command.

#### Arbitrary-reference inspection fix

Make the read-only registry contract internally consistent:

- Remove the SemVer gate from `pull_artifact`; it is a build/push constraint, not an OCI inspection constraint.
- Preserve URI syntax validation, credential-expiry checks, artifact-type handling, malicious-annotation protections,
  and all other pull safeguards.
- `margot pull`, `margot fetch`, remote `describe`, and remote `verify` must all accept an existing arbitrary/legacy OCI
  tag. No `--force` is needed merely because a tag is not SemVer.
- Build and push retain their existing SemVer validation unchanged.

#### Re-enter the existing local pipelines

The remote resolver hands the pulled static `app.yaml` to the commands as an internal explicit manifest path:

- **Verify:** call the existing `verify_service.verify` with that path. Schema A/B, template behavior (not applicable to
  a pulled static descriptor), findings, strict behavior, result dataclass, output, and exit rules remain the existing
  code path.
- **Describe:** run the existing `load_descriptor` load gate and display-model builders against that path. The remote
  artifact must receive the same YAML parsing, mapping/type gate, configuration joins, orphan observations, and
  rich-rendering protections as a local descriptor.

Do not require a downloaded remote artifact to contain a local project `margo.yaml`. The pulled `app.yaml` is the
manifest passed internally; it is a static source and therefore correctly bypasses local project resolution.

#### Remote describe identity and subtitle

Remote `describe` must identify its real source rather than expose a temporary path:

- The identity panel subtitle is `<normalized-uri> (remote)`.
- Its `OCI:` line is the same normalized URI, even though the remote artifact does not provide the local `margo.yaml`
  metadata currently used to derive that line.
- Local behavior is unchanged: the subtitle remains the local source path (with `(rendered)` for a Jinja template), and
  the OCI line remains derived from local metadata when configured.

Keep this source/OCI override at the command/display boundary or as explicit optional pure-data inputs; `domain/`
remains free of filesystem, OCI, console, and rich imports.

#### Errors and exits

All user-facing errors continue through the existing command error handling and `console.fatal`; this sprint does not
introduce a new exit-code taxonomy.

| Condition | Expected behavior | | --- | --- | | URI malformed or untagged | Existing `validate_uri` error before
network or temp-dir creation. | | URI plus `--project-dir` or `--manifest` | Shared mutual-exclusion error before I/O. |
| Credentials expired | Existing credential error, unchanged. | | Registry/ORAS failure | Existing propagated pull/fetch
failure, unchanged. | | OCI artifact not margo | Clear hard error; no best-effort descriptor parsing; direct to
`margot fetch`. | | Margo artifact lacks root `app.yaml` | Clear hard error; temp dir still removed. | | Pulled
`app.yaml` is invalid/unloadable | Existing `describe` load-gate or `verify` descriptor/schema behavior, respectively. |
| Non-SemVer but valid OCI tag | Allowed for all read-only remote commands. |

### Tests (TDD)

#### Pull/fetch regression coverage

- Arbitrary/legacy OCI tags pass URI validation and pull without `--force`; build/push SemVer tests remain unchanged.
- The shared inspection/pull path still validates malformed URIs, checks credentials, maps artifact types, and preserves
  margo-layer download behavior.

#### Shared remote resolver

- Valid margo manifest + pulled `app.yaml` returns the descriptor path and normalized URI, calls the shared pull
  mechanics with `recursive=False`, and removes the temp directory after use.
- The type gate rejects compose, quadlet, unknown, and missing `artifactType` before accepting a descriptor.
- Missing `app.yaml`, expired credentials, malformed URI, ORAS failure, and cleanup on every exception path are covered.
- A non-SemVer legacy tag succeeds through the remote resolver.

#### CLI / end-to-end coverage

- Existing local `describe` and `verify` calls retain their current behavior.
- `margot describe public.ecr.aws/g2n4p2m7/margo:1.0.0` uses the remote resolver, renders the same panels as an
  equivalent local static descriptor, and shows the URI plus `(remote)` in the identity subtitle and OCI line.
- Remote `describe --section metadata` and `--section component-first` respect the same filtering and ordering as local
  mode.
- `margot verify public.ecr.aws/g2n4p2m7/margo:1.0.0` produces the same Schema A/B results, including `--recommend`,
  `--only-recommend`, and `--strict`, as the equivalent local static descriptor.
- Both commands reject URI + `--project-dir`, URI + `--manifest`, malformed positional values, non-margo manifests, and
  missing descriptor layers without a network transfer when rejection is local.
- Command help shows the optional positional URI and preserves the local flag help.

### Documentation and definition of done (Item 1)

- Update the relevant docs command-reference pages for `describe` and `verify`: optional URI, local-vs-remote behavior, mutual
  exclusion, margo-only type gate, arbitrary existing OCI tags, temporary/non-persistent pull, remote subtitle/OCI line,
  and unchanged verification flags.
- Update the relevant user documentation (`README.md`, `docs/index.md`, and command documentation when introduced) with
  the canonical remote example `margot describe public.ecr.aws/g2n4p2m7/margo:1.0.0` and its `verify` counterpart. Do
  not use project/customer-specific references in docs.
- Remove the obsolete backlog item for reachability-only `verify --remote`; this sprint supersedes it.
- `uv run pytest` passes, including the new regression and CLI tests.
- `make docs-check` passes if docs are touched.
- Lint/type checks configured by the project pass.
- Implementation is committed in a conventional commit after all validation passes.

______________________________________________________________________

### Out of scope (Item 1)

- Checking reachability of every component referenced *inside* an application descriptor. This sprint
  validates/describes the root remote application descriptor; recursive component reachability remains future work.
- Recursive download of component artifacts. The temporary pull is `recursive=False`; commands need only the root
  `app.yaml`.
- Remote rendering of compose, quadlet, image, Helm, or unknown artifacts. They do not contain a Margo application
  description and are rejected.
- Persisting the temporary artifact or adding an output directory flag. Use `margot pull` when layers must be kept.
- `--json`, stable exit codes, JSON error envelopes, or `NO_COLOR`; those remain the separately planned Sprint 10 work.

______________________________________________________________________

## Item 2 — `margot package`: offline bundle artifacts

**Goal:** Bundle already-`build`-produced margo, compose, and quadlet outputs from `.dist/<version>/` into one
self-contained `.tgz`, for deployment into disconnected/offline environments without registry access. `package` runs
strictly after `build`; it never triggers a build itself, and it is never pushed to a registry — a bundle has no OCI
representation.

### Context: current state (verified against source)

- `services/build.py::build` writes margo's output as a plain directory at `.dist/<version>/margo/` (never a `.tgz`,
  since `_build_margo` calls `copy_tree` straight to `output_dir`), while compose/quadlet outputs are `.tgz` files
  written directly under `.dist/<version>/` via `make_tarball` (`_build_flat_component` / `_build_variant_component`).
- `domain/models.py::PackageType` is a flat `StrEnum` (`MARGO`, `COMPOSE`, `QUADLET`, `UNKNOWN`, `ALL`) mapped to OCI
  `artifactType` strings via `_ARTIFACT_TYPE_MAP` for push/pull/fetch. A bundle type must NOT enter this map — it has
  no OCI representation and is never pushed.
- `services/push.py::_resolve_registry_repository` resolves each component's `(registry, repository)` from
  component-level `repository:` in `margo.yaml`, falling back to the global top-level `repository:` field. `package`
  reuses this same precedence (component override → global fallback) minus the CLI-override tier, since `package`
  takes no registry flags.
- **Known pre-existing defect, out of scope for this item:** `_build_flat_component` resolves `output_dir =
  build_dir/version` identically for compose and quadlet, and both write `{meta.name}-{version}.tgz` into it. When
  compose and quadlet are built for the same version, quadlet's build silently overwrites compose's tgz on disk today.
  `package` must not paper over this by renaming files; see "Errors and exits" below.

### Scope

#### Bundle archive format

Archive name: `<name>-<version>.tgz` (same `<name>`/`<version>` resolution as `build`/`push`; no `-bundle` suffix).
Structure:

```
<name>-<version>.tgz
└── <name>-<version>/
    ├── app.yaml                          # recursive copy of .dist/<version>/margo/'s contents into the bundle
    │                                      # root — only the redundant top-level margo/ wrapper dir is dropped;
    ├── resources/                         # everything inside margo/ (e.g. a descriptionFile: resources/foo.md
    │   └── description.md                # target) is preserved verbatim, at its original relative path
    ├── <compose-repository>/
    │   └── <name>-<version>.tgz          # compose's built tgz, copied in verbatim — never re-extracted/re-tarred
    └── <quadlet-repository>/
        └── <name>-<version>.tgz          # quadlet's built tgz, copied in verbatim
```

- `<compose-repository>` / `<quadlet-repository>` is each component's resolved `repository` string from `margo.yaml`
  (component-level `repository:` override, else the global top-level `repository:`) — the same value `push` would
  route to. A `/`-bearing repository string (e.g. `public.ecr.aws/g2n4p2m7/margo`) becomes nested subdirectories
  naturally. This both disambiguates components pushed to different repositories and gives an offline reader instant
  navigation from `app.yaml`'s own `directory`/`repository`/`ref` fields to the matching on-disk folder, with no
  separate manifest file needed.
- No `manifest.yaml` or other bundle-level metadata file is added. `app.yaml` plus the folder names already carry
  everything needed to identify what is inside.
- No new `margo.yaml` fields. Bundle composition is entirely derived from whatever `build` already produced for the
  requested types — same `-t` semantics as `build`/`push`.
- Variant components (if `compose`/`quadlet` declares variants) each keep their own `.tgz` under their component's
  repository folder, named exactly as `build` already names them per variant.

#### `PackageType.BUNDLE`

- New `PackageType.BUNDLE` enum value in `domain/models.py`. Used only for `package`'s own `-t`/dispatch semantics.
- **Never added to `_ARTIFACT_TYPE_MAP`.** A bundle has no `artifactType`, no OCI manifest shape, and is never pushed —
  `margot push` must reject `PackageType.BUNDLE` the same way it rejects `UNKNOWN`/`ALL` today (clear `ValueError`, no
  new code path that could route a bundle through `infra/oci.py`).

#### `margot package` command

New `commands/package.py` + `services/package.py`, following the existing `commands/` → `services/` → `domain/`/
`infra/` layering exactly (mirrors `build.py`'s and `push.py`'s shape).

- Signature: `margot package [-t TYPE]... [--project-dir PATH] [--build-dir PATH] [--output PATH]`, mirroring
  `build`'s `-t` flag (repeatable, defaults to bundling everything found under `.dist/<version>/` when omitted — no
  `-t` supplied means "bundle whatever build produced," matching `build -t all`'s "skip what's undefined" spirit, see
  below).
- Requires prior `build` output to exist. `package` never builds; if `.dist/<version>/` (or the specific requested
  type's output within it) is missing, fail with a clear error directing the user to run `margot build` first — no
  implicit build-then-package.
- Output path: `.dist/<version>/<name>-<version>.tgz` by default; `--output` overrides the destination path.
- Reuses `domain/tags.py` SemVer/OCI-tag validation for `<version>`, consistent with `build`/`push`.

#### `-t` filter and skip/fail semantics

1. **Default (no `-t`):** bundle everything found under `.dist/<version>/` — margo (always present, `build` requires
   it), plus compose and/or quadlet if their build outputs exist on disk.
2. **Explicit `-t`:** bundle only the requested type(s). If a requested type's build output is missing from
   `.dist/<version>/`, hard-fail with a clear error naming the missing type and directing the user to `margot build
   -t <type>` first — the same way `build -t compose` itself hard-fails when `compose:` is undefined in `margo.yaml`.
   This mirrors `_build_all`'s distinction exactly: silently skipping a type is only correct when that type was never
   defined at all (mirrors `_build_all`'s `ValueError` message match for "not defined in margo.yaml"); requesting a
   type that was defined but never built is a hard error, not a skip.
3. **Collision guard:** before writing any component into the bundle, `package` must detect if two components resolve
   to the same `(repository, filename)` pair inside the bundle (the pre-existing `build` collision described above).
   If detected, hard-fail with a clear error naming both colliding types and repositories, and do not silently
   overwrite one with the other inside the bundle. This is a deliberate refusal, not a workaround for the underlying
   `build` defect — fixing that defect is out of scope for this item.

### Tests (TDD)

- `domain/models.py`: `PackageType.BUNDLE` exists and is absent from `_ARTIFACT_TYPE_MAP`; `artifact_type_to_package_type`
  never returns `BUNDLE`.
- `services/package.py`: bundling margo-only, margo+compose, margo+quadlet, and all three; correct nested-folder
  naming from component-level vs. global `repository:`; recursive preservation of margo's internal subdirectories
  (e.g. a `resources/` folder survives unflattened); explicit `-t` for an undefined type fails with the `build`-style
  "not defined in margo.yaml" message; explicit `-t` for a defined-but-unbuilt type fails with a distinct "run
  `margot build` first" message; the repository/filename collision guard fails clearly and writes no partial/
  overwritten bundle.
- `services/push.py`: pushing `PackageType.BUNDLE` raises the same class of `ValueError` as pushing `UNKNOWN`/`ALL`.
- CLI/e2e: `margot package`, `margot package -t compose`, `--output` override, missing `.dist/<version>/` error,
  missing-build-output error, and the full round-trip (`build` → `package` → extract → verify expected tree shape).

### Documentation and definition of done (Item 2)

- New `docs/commands/package.md`: synopsis, flag table, archive format diagram, `-t`/skip-vs-fail semantics, the
  "never pushed" contract, and a runnable example using `public.ecr.aws/g2n4p2m7/margo:1.0.0`-style naming.
- `README.md` command table gains `package`; a short "Package for offline delivery" section next to the existing
  "Build and push" section.
- `ROADMAP.md`: remove/resolve the "More artifact types in `fetch`" ambiguity only if affected; otherwise no change
  needed since this is new-in-conversation work, not a pre-existing backlog line.
- `uv run pytest` passes, including new Item 2 tests.
- `make docs-check` passes.
- Lint/type checks configured by the project pass.
- Implementation is committed in a conventional commit after all validation passes, on its own branch/worktree per
  `agent-workspace`, independent of Item 1's branch.

### Out of scope (Item 2)

- Container-image inclusion in the bundle. Promoted to its own Item 3 below (not designed as part of Item 2).
- Fixing the pre-existing compose/quadlet same-repository-same-version tgz collision inside `build` itself — `package`
  only detects and refuses it, per the collision guard above.
- Pushing, registering, or giving a bundle any OCI representation. A bundle is a local file handoff only.
- Any new `margo.yaml` fields for bundle composition or manifest metadata.
- Nested/recursive re-extraction or re-tarring of compose/quadlet component archives — they are always embedded
  opaque.

______________________________________________________________________

## Item 3 — Container image inclusion in offline bundles

**Goal:** Extend `margot package` (Item 2) to embed the container images referenced by a component's `image:` block
into the bundle **by default**, so the resulting `.tgz` is fully self-contained for an offline/disconnected
deployment — no registry access needed to `podman load` the images referenced by the bundled compose/quadlet content.
An explicit `--no-images` flag opts back out to Item 2's pure-local, no-network behavior.

**Behavior-change note:** this makes default `margot package` (with no flags) a **network-dependent** operation for
the first time — it contacts an image registry and may require credentials, where Item 2 alone is purely local/
offline. This is a deliberate, visible contract change and must be called out prominently in `docs/commands/package.md`
and in the CLI's own `--help` text, not just in this sprint file — a user relying on `package` for fully offline/
air-gapped builds needs `--no-images` to be immediately discoverable.

### Context: current state (verified against source)

- `domain/metadata.py::ImageConfig` holds `search`/`replace` — a literal string pair rendered into compose/quadlet
  content at build time via `_render_image_pair` (`services/build.py`). `replace` is a Jinja2-rendered template string
  resolving to the real production image reference (e.g. `public.ecr.aws/g2n4p2m7/my-app:1.0.0`); `search` is the
  dev-local placeholder it replaces. margot has never resolved, pulled, or otherwise contacted an image registry for
  either value — `image:` today is pure text substitution.
- margot has **no external binary dependency** for OCI operations (`tech.md`: "oras-py over ORAS CLI subprocess ...
  no external binary dependency"). This item must hold that constraint: no shelling out to `podman save` / `skopeo
  copy` / `docker save`.
- `infra/oci.py::OrasClient.get_manifest` / `.download_blob` already fetch arbitrary OCI manifests and blobs for
  margot's own artifact types; a container image is retrievable through the exact same primitives — an image manifest
  (or multi-platform image *index*) plus a config blob and gzipped layer blobs, just with different `mediaType`
  values than margot's own layer types.
- The most runtime-agnostic on-disk archive shape for a saved image is the **OCI image layout** (`oci-layout` +
  `index.json` + `blobs/sha256/...`, per the OCI Image Spec) — this is what `podman save --format oci-archive`
  produces, and it loads via `podman load`, `docker load` (current versions), `skopeo copy`, and any OCI-compliant
  runtime. It is preferred over `docker-archive` (Docker's own legacy v2 manifest format, podman's *default* `save`
  format) specifically because it isn't tied to one vendor's manifest shape.

### Scope

#### Which image reference is pulled

- Only the rendered **`replace`** value is pulled (per your #1) — the real production image reference the deployment
  will actually run. The `search` placeholder is never fetched.
- Resolve the image reference **by re-reading it from the already-built component content**, not by re-rendering
  `ImageConfig` from `margo.yaml` a second time (per your #1 — "search it in the component, it's easier"). The
  rendered `replace` value is already present verbatim in the built compose/quadlet `.tgz` content under
  `.dist/<version>/`; `package` extracts/greps the built content for the image reference(s) actually present, rather
  than recomputing the Jinja2 render path a second time and risking drift between what was built and what gets
  bundled. Exact mechanism (parse compose YAML `image:` fields vs. quadlet `Image=` directives vs. a generic
  reference-shaped string scan) needs to be pinned down at implementation time per component format — this sprint
  item does not redesign compose/quadlet parsing, it adds a read-only extraction pass over already-built content.

#### How the image is fetched and saved

- Pull the image manifest (or index, for multi-platform) and its blobs via the existing `infra/oci.py::OrasClient`
  primitives (`get_manifest`, `download_blob`) — **no new binary dependency**, consistent with `tech.md`.
- Assemble the pulled manifest + config + layer blobs into a standalone **OCI image layout tar**
  (`oci-layout` + `index.json` + `blobs/sha256/...`) — the agnostic format from the Context section above. This is
  new logic in `infra/oci.py` (or a sibling `infra/` module), not a call to an external `podman`/`skopeo` binary.

#### Where saved images live in the bundle

- New `images/` folder at the bundle root, one OCI-layout tar per image, named by the image's own
  `<repository>:<tag>` the way `podman save` already names its output on export (per your #3 — export naming already
  avoids overwrites, since it's keyed by the full reference including tag). Two components referencing the same
  image reference share one saved tar; two different tags of the same repository or different repositories both get
  distinct files, so no additional collision handling is needed beyond what reference-based naming already gives.
- Updated bundle structure:

```
<name>-<version>.tgz
└── <name>-<version>/
    ├── app.yaml
    ├── resources/
    │   └── description.md
    ├── images/
    │   └── <repository>_<tag>.tar        # OCI image layout tar, one per distinct referenced image
    ├── <compose-repository>/
    │   └── <name>-<version>.tgz
    └── <quadlet-repository>/
        └── <name>-<version>.tgz
```

  (Exact filename sanitization for `/`- and `:`-bearing repository/tag strings follows the same sanitize pattern
  `infra/layers.py::sanitize_filename` already uses for layer filenames — reuse it rather than inventing new
  sanitization rules.)

#### Flag surface

- Image inclusion is the **default** behavior of `margot package` from this item onward — no opt-in flag required.
  A new `--no-images` flag opts back out, restoring Item 2's exact pure-local/no-network/no-registry-contact behavior
  (no image resolution, no `images/` folder). This is the only supported way to get offline-build behavior without
  registry access once this item ships.
- Because default behavior now contacts a registry, `package` must reuse the existing credential-expiry check
  (`infra/credentials.py::check_credentials`) the same way `pull`/`fetch`/`push` already do, before attempting any
  image manifest pull — an expired-credential error must surface clearly, not as a generic network failure.
- Multi-platform selection (which platform(s) of a multi-arch index get pulled) is explicitly **deferred to Item 4**
  (per your #4): this item's default is "pull every platform present in the index," with per-platform filtering
  designed and flagged separately in Item 4. Do not design the filter flag here.

### Tests (TDD)

- Extraction: given already-built compose/quadlet content containing a rendered image reference, `package` (default,
  no flag) correctly identifies the reference(s) present, with no re-render of `ImageConfig`.
- `infra/oci.py`: pulling an arbitrary image manifest/index + blobs via `get_manifest`/`download_blob` and assembling
  a valid OCI image-layout tar (`oci-layout`, `index.json`, `blobs/sha256/...` all present and internally consistent)
  — verified against a mocked ORAS client, no live registry contact.
  - Multi-platform index: all platforms present in the index are pulled by default (Item 4 will add filtering).
- Bundle structure: `images/` appears by default and is absent only with `--no-images`; two components sharing one
  image reference produce one saved tar, not two; distinct tags/repositories never collide.
- Credential check: expired credentials produce the existing clear credential error before any manifest pull is
  attempted; `--no-images` skips the credential check entirely (no registry contact at all).
- CLI/e2e: default `margot package` end-to-end against a mocked registry, extract, and verify the resulting
  `images/*.tar` loads as a valid OCI image layout (structural check, not an actual `podman load`);
  `margot package --no-images` end-to-end confirms zero registry contact and Item 2's exact prior output shape.

### Documentation and definition of done (Item 3)

- `docs/commands/package.md` gains the default-on image inclusion contract, the `--no-images` opt-out, the
  network-dependency behavior-change callout (with a dedicated admonition per `documentation.md`'s sparing-use rule —
  this qualifies as something that "would otherwise cause a mistake"), the OCI-image-layout format choice and why
  (vs. `docker-archive`), the `images/` folder shape, and an explicit "run `podman load -i images/<file>.tar` before
  deploying offline" usage note.
- `--help` text for `margot package` states plainly that images are included by default and that `--no-images`
  restores fully offline/no-network behavior.
- `uv run pytest` passes, including new Item 3 tests.
- `make docs-check` passes.
- Lint/type checks configured by the project pass.
- Implementation is committed in a conventional commit after all validation passes, on its own branch/worktree per
  `agent-workspace`, independent of Items 1 and 2's branches (depends on Item 2's bundle command existing first, so
  its branch should be based on or merged after Item 2's, not developed fully in parallel from the same base).

### Out of scope (Item 3)

- Multi-platform filtering flag (which architecture(s) to pull) — Item 5.
- Local container-daemon lookup (checking Podman/Docker local storage before the registry) — Item 4. Item 3 alone is
  registry-only: if an image referenced by `replace` has not been pushed to the registry it names, `package` fails
  clearly rather than finding it locally.
- Re-deriving the image reference from `margo.yaml`'s `ImageConfig` template a second time — extraction reads already-
  built content instead (per your #1).
- Shelling out to `podman`/`skopeo`/`docker` binaries for the save step — pulled and assembled via `infra/oci.py`
  directly.
- Image signing, verification, or vulnerability scanning of bundled images.
- Any change to `margo.yaml`'s existing `image: {search, replace}` schema.

______________________________________________________________________

## Item 4 — Local container-daemon lookup for bundled images

**Goal:** Before falling back to Item 3's registry pull, let `margot package` check whether an image is already
present in a local container daemon (Podman or Docker) and, if so, save it from there — covering the case where a
developer has built/tagged an image locally that has not been pushed to any registry yet. Runs in parallel with Item 5
(both depend only on Item 3, not on each other).

### Context: current state (verified against source)

- Item 3 is registry-only: it resolves and pulls the image named by a component's rendered `replace` value exclusively
  through `infra/oci.py::OrasClient` against the registry that reference points to. It has no notion of a local
  container runtime.
- `environment.md` (this project's own contributor/dev-machine convention) states the *contributor's* local machine
  runs Podman only, rootless, never a Docker daemon. That is a convention for working on margot's own source, not a
  constraint on margot's product design — margot's users are not required to run Podman. Docker remains the more
  common daemon among margot's actual audience, so both must be supported for margot to stay environment-friendly.
- Two non-interchangeable Python SDKs exist for this: `podman` (PyPI package `podman`, ~120 KB, talks to the Podman
  libpod REST API over a Unix/TCP socket) and `docker` (PyPI package `docker`, the Docker SDK for Python, talks to the
  Docker Engine API). Neither wraps the other's daemon — both are needed as separate optional dependencies to cover
  both runtimes.
- **Format asymmetry, verified:** the Podman libpod image-export API accepts a `format` parameter and can return an
  **OCI-archive** natively — no conversion needed on the Podman path. The Docker Engine API's image-export endpoint
  has **no OCI-archive option**; it only ever returns Docker's own legacy tarball format. The Docker path therefore
  requires new conversion logic in margot (Docker-tarball → OCI image-layout: unpack Docker's manifest+config+layers,
  re-wrap as `oci-layout` + `index.json` + `blobs/sha256/...`) to keep every `images/*.tar` in a bundle uniformly
  shaped regardless of source, matching Item 3's registry-sourced tars (per your #3 — normalize, don't mix formats).

### Scope

#### `--runtime` flag and auto-probe default

- New `margot package --runtime podman|docker|none` flag.
  - `podman` / `docker`: force lookup against that specific daemon only; if the image isn't found there, fall back to
    Item 3's registry pull (per your #2 — local-first, registry-fallback). Does not also try the other daemon.
  - `none`: skip daemon lookup entirely, registry-only — exactly Item 3's own behavior with no daemon precondition.
  - **Omitted (default): silent auto-probe** (per your explicit confirmation) — try the Podman socket, then the
    Docker socket, then fall back to the registry. No daemon reachable is not an error at this stage; it silently
    proceeds to the registry pull, since a daemon is an optional accelerant, not a requirement.
- Socket paths use each SDK's own standard local-connection defaults (e.g. Podman's `unix:///run/user/<uid>/podman/
  podman.sock`, Docker's default local socket) — margot does not invent new discovery logic beyond what each SDK
  already provides for "connect to the local daemon."
- `--runtime` combined with `--no-images` is meaningless (nothing to look up); fail clearly, matching Item 5's own
  `--platform` + `--no-images` mutual-exclusion precedent — do not silently ignore `--runtime`.

#### Local lookup and save

1. For the resolved `replace` image reference, check the selected/probed daemon for a locally-present image matching
   that exact reference (repository + tag).
2. If found on **Podman**: export directly via the libpod API's OCI-archive format option — no conversion step.
3. If found on **Docker**: export via the Docker SDK (Docker's own tarball format is the only option at the API
   level), then normalize/re-wrap it into the same OCI image-layout shape Item 3 already uses, so the bundle's
   `images/` folder is format-uniform regardless of source.
4. If not found on the probed/selected daemon(s) (or `--runtime none`), fall back to Item 3's registry pull unchanged.
5. A locally-found image is used as-is — this item does not compare or reconcile a local image's content against
   what the registry holds for the same reference; local-first means local wins when present, with no digest
   cross-check against the registry copy.

#### New dependencies and precondition

- New pinned dependencies: `podman` (Podman SDK, PyPI package `podman`) and `docker` (Docker SDK for Python, PyPI
  package `docker`) — both exact-pinned per `code-conventions.md`. Both are small; neither is a binary dependency
  (they are HTTP/socket clients, not the `podman`/`docker` CLI), so `tech.md`'s "no external binary dependency" claim
  for OCI operations is unaffected. This is, however, margot's first feature with an optional reachable-daemon
  precondition — call this out explicitly in docs rather than treat it as equivalent to margot's existing pure-registry
  model.
- A reachable daemon is always optional: absence of any daemon (or a permissions/socket error probing one) is not a
  hard failure — it degrades to Item 3's registry-only path, logged at `info`/`debug` per `code-conventions.md`
  layering (not surfaced as a user-facing warning unless `--runtime` explicitly forced a daemon that turned out to be
  unreachable, which **is** a clear error, since the user asked for that specific daemon).

### Tests (TDD)

- `--runtime podman` / `--runtime docker`: found-locally path saves correctly (OCI-archive direct for Podman,
  normalized-from-Docker-tarball for Docker); not-found-locally path falls back to the registry pull unchanged from
  Item 3.
- `--runtime none`: identical output to Item 3 alone; no daemon socket contacted at all (mockable/assertable).
- Default (no `--runtime`): auto-probe order is Podman → Docker → registry; each stage's absence/failure falls through
  to the next without raising.
- `--runtime` forced to an unreachable daemon: clear error, no silent fallback to the registry.
- Docker-tarball → OCI-image-layout normalization produces a structurally valid `oci-layout`/`index.json`/
  `blobs/sha256/...` tar, verified the same way Item 3's registry-sourced tars are verified — both must be
  structurally indistinguishable in shape.
- `--runtime` combined with `--no-images` fails clearly.
- All daemon interactions are mocked at the SDK client boundary; no test requires an actually-running Podman/Docker
  daemon or contacts a live registry.

### Documentation and definition of done (Item 4)

- `docs/commands/package.md` gains the `--runtime` flag (all three values plus the silent-auto-probe default), the
  new optional daemon precondition (explicitly marked as new/optional, not required), and the local-first/
  registry-fallback precedence.
- `pyproject.toml` gains the two new exact-pinned dependencies; note their small footprint if relevant to a
  dependency-audit note in `CONTRIBUTING.md`, if such a note exists.
- `uv run pytest` passes, including new Item 4 tests.
- `make docs-check` passes.
- Lint/type checks configured by the project pass.
- Implementation is committed in a conventional commit after all validation passes, on its own branch/worktree per
  `agent-workspace`, based on or after Item 3's branch (depends on Item 3's image-pull contract existing first, but
  is independent of and can run in parallel with Item 5).

### Out of scope (Item 4)

- Multi-platform filtering — Item 5, unaffected by this item; a locally-found image is saved as whatever
  platform(s) the local daemon actually has stored for that reference, with no separate platform selection logic here.
- Reconciling or digest-comparing a locally-found image against the registry's copy of the same reference — local
  presence always wins without a cross-check.
- TCP-based remote daemon connections — only local Unix-socket daemon discovery is in scope; a remote
  `DOCKER_HOST`/Podman TCP endpoint is not addressed.
- Building or tagging images — this item only looks up and exports images that already exist locally; it never
  invokes a build.

______________________________________________________________________

## Item 5 — Multi-platform filtering for bundled images

**Goal:** Let `margot package` filter which platform(s) of a multi-arch image index get pulled and saved, rather than
always saving every platform present (Item 3's default). Purely additive on top of Item 3; does not change how images
are pulled, assembled, or named. Independent of Item 4; both depend only on Item 3.

### Context: current state (verified against source)

- Item 3 pulls and saves **every platform present** in a multi-arch image index by default, with no filtering
  mechanism. This item adds the filter only — it does not touch Item 3's pull/assemble/naming logic otherwise.
- The OCI Image Spec's image index (`application/vnd.oci.image.index.v1+json`) carries a `platform: {os, architecture,
  variant?}` object per child manifest — the same `os/arch` shape Docker, podman, and OCI tooling already expose via
  `--platform os/arch` flags (e.g. `linux/amd64`, `linux/arm64`, `linux/arm/v7`).

### Scope

#### `--platform` flag

- New `margot package --platform <os>/<arch>` flag, repeatable (`--platform linux/amd64 --platform linux/arm64`),
  following the `os/arch` convention already standard across Docker/podman/OCI tooling — no new convention invented.
- **Default unchanged from Item 3:** omitting `--platform` entirely still pulls and saves every platform present in
  the index. `--platform` is purely a narrowing filter, never required.
- Only meaningful combined with default (or explicit, once Item 3 ships) image inclusion; if `--no-images` is also
  passed, `--platform` has nothing to filter — this combination should fail clearly (mutually pointless flags) rather
  than silently ignoring `--platform`.
- Applies only to the registry-pull path (Item 3). If Item 4's local-daemon lookup finds the image locally first,
  `--platform` does not apply to that locally-sourced image — see Item 4's own out-of-scope note.

#### Validation

- An `--platform` value that isn't a valid `os/arch` (or `os/arch/variant`) shape fails clearly before any registry
  contact.
- A requested platform absent from the actual pulled index fails clearly, naming both the requested platform(s) and
  the platform(s) actually present in the index — never silently produces an empty or partial image-layout tar for a
  platform that doesn't exist in the source image.
- A single-platform (non-index) image manifest with a `--platform` filter that doesn't match it is treated the same
  way — clear error, not a silent no-op.

### Tests (TDD)

- Valid `--platform` values narrow the saved `images/` tars to exactly the requested platform(s), verified against a
  mocked multi-arch index fixture.
- Invalid `os/arch` syntax fails before registry contact.
- A requested-but-absent platform fails with a clear message naming both what was requested and what the index
  actually contains.
- `--platform` combined with `--no-images` fails clearly rather than silently doing nothing.
- Omitting `--platform` preserves Item 3's exact "pull everything" default — no regression.

### Documentation and definition of done (Item 5)

- `docs/commands/package.md` gains the `--platform` flag: syntax, repeatable usage, default-is-everything behavior,
  and the `--platform` + `--no-images` mutual-exclusion error.
- `uv run pytest` passes, including new Item 5 tests.
- `make docs-check` passes.
- Lint/type checks configured by the project pass.
- Implementation is committed in a conventional commit after all validation passes, on its own branch/worktree per
  `agent-workspace`, based on or after Item 3's branch (depends on Item 3's pull/index-handling existing first, but
  is independent of and can run in parallel with Item 4).

### Out of scope (Item 5)

- Any change to how a selected platform's manifest is pulled, assembled into an OCI image-layout tar, or named —
  Item 3's contract is unchanged; this item only decides *which* platforms proceed through that unchanged pipeline.
- Auto-detecting the host's own platform as an implicit default filter — the default stays "everything," matching
  your explicit instruction; an implicit host-platform default was not requested and would be a silent behavior
  narrowing.
