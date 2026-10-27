# Sprint 15 — Helm charts on the pull side: detect, pull, recurse, bundle

**Status:** draft — Sprint 14 fully designed (2026-10-16); Sprint 15 design updated; helm manifest annotations/media types verified against a real chart (2026-10-16)
**Type:** feature
**Owner:** python-dev (docs: docs-writer)
**Release:** planned for `release/X.Y.Z` (TBD, after Sprint 14)

---

## 1. Goal

margot recognises Helm charts stored in OCI registries and handles them like the other
component types: `margot pull` downloads them, `pull --recursive` follows helm components
declared in an `app.yaml`, `margot package` can include them in an offline bundle, and
`margot migrate --components` handles helm components the same way it handles compose and
quadlet — pull the artifact and organise it into a directory.
Nothing in this sprint needs the `helm` binary — charts are plain OCI artifacts and are
downloaded with oras-py.

---

## 2. Context

- Artifact type detection is by the manifest's `artifactType` only
  (`domain/models.py::_ARTIFACT_TYPE_MAP`, `artifact_type_to_package_type`). Helm charts do not
  set an `artifactType`; they are identified by the config media type
  `application/vnd.cncf.helm.config.v1+json` and the layer media type
  `application/vnd.cncf.helm.chart.content.v1.tar+gzip`. Today a helm chart is `UNKNOWN`: `pull`
  refuses it without `--force`, and `pull --recursive` logs a warning per helm component
  ("Failed to pull component ...").
- `pull` of compose/quadlet downloads layers selected by media type and names files with
  `domain/layers.py::resolve_filename` (layer title → manifest annotations `<title>-<version>.tgz`
  → digest). **Verified (2026-10-16) against a real helm chart:** helm writes the standard OCI
  manifest-level annotations `org.opencontainers.image.title` / `org.opencontainers.image.version`
  that `resolve_filename` already reads — margot reads what helm writes and adds no annotations of
  its own (see §3.3).
- `package` bundles build outputs and discovers images inside compose/quadlet components.
- Sprint 13 documents helm as "warned, not representable" in `migrate --components`. Sprint 14
  makes it representable (`PackageType.HELM`, helm layer media types); this sprint extends
  `migrate --components` to handle helm components exactly like compose/quadlet — pull the
  artifact and organise into a directory (owner decision, 2026-10-16). The "warned, not
  representable" path is removed.
- Sprint 14 ships `--plain-http` as a real global flag applied uniformly to the oras-py registry
  path. `pull`, `pull --recursive`, and the integration tests in this sprint inherit it for free —
  no additional wiring needed here.
- The backlog item "More artifact types" contained helm detection; it moves here.
- `fetch` currently pretty-prints raw manifest JSON for any artifact type — no classification.
  Adding helm-specific classification to `fetch` is a separate, non-trivial change; it stays in
  the backlog (owner decision, 2026-10-16).

Dependencies: **Sprint 14** (`PackageType.HELM`, `helm:` block, media-type notes, `--plain-http`).

---

## 3. Authoritative Design

### 3.1 Scope

**In scope:** helm detection from the manifest; `pull` of a helm chart; `pull --recursive`
including helm components; `package` bundling of built helm archives; `migrate --components`
handling helm the same way as compose/quadlet (pull artifact, organise into directory, remove
the "warned, not representable" path).

**Out of scope:** discovering container images inside charts (requires `helm template` and a
host helm); signing/provenance layers; HTTP chart repositories; `fetch` helm classification
(raw pretty-print is consistent for all types today; classification stays in the backlog).

### 3.2 Item 1 — Detection

Detection must look beyond `artifactType`: a helm chart is recognised when the config
descriptor's `mediaType` is the helm config type **or** a layer carries the helm chart layer
type. The two helm media types are added as named constants in `domain/layers.py` (Sprint 14
already adds them to `oci-media-types.md` as a reference; this sprint makes them code).

**Detection interface:** introduce a new `detect_package_type(manifest: dict) -> PackageType`
function in `domain/models.py` (or `domain/layers.py` — wherever `artifact_type_to_package_type`
lives) that:
1. First tries `artifact_type_to_package_type` (existing fast path for `artifactType`-tagged
   artifacts: margo, compose, quadlet).
2. Falls back to inspecting `config.mediaType` and layer `mediaType` fields for types that don't
   set `artifactType` — helm is the first and currently only case.

All existing call sites in `pull` and `pull --recursive` switch to `detect_package_type`;
`artifact_type_to_package_type` stays as an internal function (no call sites outside
`detect_package_type`). `domain/` stays pure — no I/O, the manifest dict is passed in by the
caller.

### 3.3 Item 2 — Pull

**Principle (owner, 2026-10-16): margot does not own the helm artifact format — helm does.**
margot never adds, standardises, or requires any annotation on a helm chart; it reads only the
standard OCI annotations helm already writes, through the code path margot already has for
compose/quadlet. Being compatible with helm means letting helm's own layout stand.

Verified against the real `sensor-dashboard:1.2.3_helm-x` chart pushed to the local zot
(2026-10-16) — this is exactly what helm 4.2 writes:

- `config.mediaType` = `application/vnd.cncf.helm.config.v1+json`.
- One layer, `mediaType` = `application/vnd.cncf.helm.chart.content.v1.tar+gzip`, **bare** (no
  `org.opencontainers.image.title` on the layer).
- Manifest-level `annotations` carry `org.opencontainers.image.title` (`sensor-dashboard`) and
  `org.opencontainers.image.version` (`1.2.3+helm-x` — the `+` is restored on the annotation even
  though the OCI tag is `1.2.3_helm-x`), plus description/created/authors and any `Chart.yaml`
  annotations passed through.

Design:

- Select the chart layer by the helm layer media type.
- Name the file `<title>-<version>.tgz` from the **manifest-level** `org.opencontainers.image.title`
  / `org.opencontainers.image.version` annotations, falling back to the digest when absent — this
  is exactly `resolve_filename`'s existing manifest-annotation path; no new annotation handling is
  added. For this chart the result is `sensor-dashboard-1.2.3+helm-x.tgz`, matching what `helm pull`
  itself produces. (Helm sets no layer-level title, so the "layer title" step of the existing order
  simply finds nothing and moves on — no code change needed there.)
- Honour the existing filename sanitisation and `--force` rules.
- `PackageType.HELM` is accepted by `--force-type`-style overrides wherever the other types are.

### 3.4 Item 3 — `pull --recursive`

- Helm components in `app.yaml` (`properties.repository` + `properties.revision`) are pulled into
  `<outdir>/<sanitised component name>/` like compose/quadlet. Sprint 13 Item 1 owns the
  component-name sanitisation; this sprint must not regress it.
- `properties.revision` holds the `_` form of the tag (the real OCI tag, per the `+`↔`_`
  convention established in Sprint 14 S1) — passed to oras-py as-is, no conversion needed.
- A failure to pull one component stays a warning for that component, as today.

### 3.5 Item 4 — `package`

- Built helm archives (from Sprint 14's `.dist/<version>/`) are included in the bundle with the
  same collision checks as compose/quadlet, and appear in `-t` selection: `-t helm` bundles only
  helm archives, `-t all` includes helm alongside compose/quadlet/margo (same pattern as
  build/push).
- No image discovery for helm charts in this sprint; document the limitation: images referenced
  only inside a chart are not bundled.

### 3.6 Item 5 — `migrate --components` for helm

Sprint 13 documented helm as "warned, not representable" in `migrate --components`. Sprint 14
makes helm representable; this sprint removes that warning and handles helm components exactly
like compose/quadlet:

- Detection uses `detect_package_type` (Item 1) — the same function used by `pull`.
- Pull the helm artifact into the appropriate directory (`helm/<component-name>/` mirroring
  `compose/` and `quadlet/`).
- The "warned, not representable" code path in `migrate --components` is removed.
- Safe extraction and collision rules from Sprint 13 apply unchanged.
- No `helm` binary needed — plain OCI pull via oras-py, same as Items 2–4.

### 3.7 Non-goals

No `helm` binary use; no change to `push`; no change to `build`; no `fetch` classification.

---

## 4. Checkable Steps

- [x] **Annotation spike (done 2026-10-16):** real helm chart manifest inspected
  (`sensor-dashboard:1.2.3_helm-x` in local zot). Confirmed: config
  `application/vnd.cncf.helm.config.v1+json`; one bare layer
  `application/vnd.cncf.helm.chart.content.v1.tar+gzip`; manifest-level
  `org.opencontainers.image.title`/`.version` (version keeps `+`). margot reads these via the
  existing `resolve_filename` path and adds no annotations. See §3.3.
- [ ] `detect_package_type` function + helm media type constants + unit tests (helm chart detected
  by config type, helm chart detected by layer type, compose/quadlet/margo still work, unknown
  stays unknown).
- [ ] All `pull` / `pull --recursive` call sites switch from `artifact_type_to_package_type` to
  `detect_package_type`; no existing behaviour changes.
- [ ] `pull` of a helm chart: layer selection by media type, filename from annotations, integration
  test against a faked/real registry.
- [ ] `pull --recursive` with a helm component in `app.yaml`; confirm `revision` (`_` form) is
  passed to oras-py as-is; component-name sanitisation not regressed.
- [ ] `package` includes helm archives; `-t helm` and `-t all` selection; collision tests; document
  the "images inside charts not bundled" limitation.
- [ ] `migrate --components`: remove "warned, not representable" path for helm; pull into
  `helm/<component-name>/` directory; tests (helm component migrated, compose/quadlet unaffected).
- [ ] Docs: `pull`, `package`, `migrate`, concepts pages; remove "helm unsupported" wording;
  update Sprint 13's `migrate --components` helm note.
- [ ] `make docs-check` passes.
- [ ] Each task committed as one or more conventional commits.

---

## 5. Definition of Done

- [ ] All checkable steps completed.
- [ ] `make check` passes (no helm binary required).
- [x] Annotation spike completed (2026-10-16); filename logic reads helm's own OCI annotations, no
  annotations added by margot (§3.3).
- [ ] `migrate --components` helm path exercised in tests; "warned, not representable" path gone.
- [ ] Docs updated and `make docs-check` passes.
- [ ] No TODOs left (or deferred with `# TODO(kiro): ...` and a ROADMAP entry).
- [ ] Each task committed as one or more commits on the feature branch — no bulk commit.
- [ ] Handed back for review (Gate 2).

---

## 6. Close-out Note

```text
(filled in after merge)
```

---

## References

- [sprint-14.md](./sprint-14.md) — build and push.
- [sprint-13.md](./sprint-13.md) — `migrate --components` and recursive-pull sanitisation.
- [oci-media-types.md](../steering/oci-media-types.md)
