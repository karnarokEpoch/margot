# Sprint 9 — Shared remote OCI resolution for `describe` and `verify`

**Goal:** Let `margot describe` and `margot verify` inspect a published Margo application artifact directly, using the
same OCI inspection and layer-pull mechanics as `fetch` and `pull`. A command with no positional URI remains
local-project behavior; a command with a URI validates, pulls the remote margo artifact into a temporary directory, and
then runs the existing local descriptor pipeline against that downloaded `app.yaml`.

This finishes the remote `describe` capability that was planned in Sprint 8 but did not land in release 0.8.0, and
extends the same capability to `verify`. It replaces the previous backlog concept of `verify --remote` reachability-only
checks with actual remote descriptor validation.

**Prerequisite:** Sprint 8's local `describe` views are released. The former Sprint 9 machine-output/error-code plan has
been renumbered to Sprint 10.

______________________________________________________________________

## Context: current state (verified against source)

- `describe` and `verify` currently resolve only local files: an explicit `--manifest`, or `margo.yaml` in
  `--project-dir` followed by `app.yaml.jinja` / `app.yaml` resolution. Neither command accepts a positional URI.
- `services/verify.py::resolve_descriptor` is the shared local resolution mechanism. An explicit static `app.yaml`
  bypasses `margo.yaml`, which makes it suitable for a downloaded remote descriptor; `describe` layers its YAML-mapping
  and `kind: ApplicationDescription` load gate on top of this resolver.
- `services/fetch.py::fetch_manifest` already normalizes an optional `oci://` scheme, validates the OCI reference,
  checks credential expiry, and obtains a manifest through `infra/oci.py::OrasClient`.
- `services/pull.py::pull_artifact` performs the same registry checks and downloads artifact layers. Margo artifacts use
  the ORAS pull path and write their layers, including `app.yaml`, to the caller-provided output directory.
- `pull_artifact` currently adds a SemVer gate that conflicts with `FEATURES.md`'s documented behavior: `pull` and
  `fetch` are inspection commands and must retrieve arbitrary existing OCI references, including legacy tags. This
  defect would reject remote inspection references such as `public.ecr.aws/g2n4p2m7/margo:1.1.0_legacy-manifest`.
- `artifact_type_to_package_type` maps the OCI manifest's `artifactType` to `PackageType`. Only `PackageType.MARGO`
  contains an application description; compose, quadlet, and unknown artifacts must fail before their layers are
  accepted by `describe` or `verify`.

______________________________________________________________________

## Scope

### Item 1 — Optional remote OCI URI for `describe` and `verify`

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

Add expected-behavior tests before or alongside implementation. Mock the ORAS client at the `infra/oci.py` boundary; no
test contacts a live registry.

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

### Documentation and definition of done

- Update `FEATURES.md` command contracts for `describe` and `verify`: optional URI, local-vs-remote behavior, mutual
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

## Out of scope

- Checking reachability of every component referenced *inside* an application descriptor. This sprint
  validates/describes the root remote application descriptor; recursive component reachability remains future work.
- Recursive download of component artifacts. The temporary pull is `recursive=False`; commands need only the root
  `app.yaml`.
- Remote rendering of compose, quadlet, image, Helm, or unknown artifacts. They do not contain a Margo application
  description and are rejected.
- Persisting the temporary artifact or adding an output directory flag. Use `margot pull` when layers must be kept.
- `--json`, stable exit codes, JSON error envelopes, or `NO_COLOR`; those remain the separately planned Sprint 10 work.
