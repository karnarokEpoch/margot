# Sprint 11 — Margo resource media types driven by `app.yaml`

**Status:** in-flight
**Type:** fix
**Owner:** python-dev
**Release:** planned for `release/X.Y.Z` (TBD, after Sprint 10)

---

## 1. Goal

Make `margot push` ship every resource file an `app.yaml` actually references (any
extension — not just the four hardcoded names/types it supports today), typed by its real
extension, plus any additional file a developer drops under `resources/` with a generic
fallback media type. Fix `describe`/`verify`/`pull --recursive`'s descriptor-layer lookup
to key off the OCI layer `mediaType`, not the literal filename `app.yaml`.

---

## 2. Context

Two related correctness bugs found in manual testing (2026-10-15):

**Bug 1 — SVG icon silently dropped by `push`.** A project declared `icon:
resources/icon.svg` in `app.yaml`. `margot build` stages the margo source dir correctly,
but `margot push` never ships the file: `infra/oci.py::push_margo` has a hardcoded,
closed list of exactly four optional resource files —

```python
optional = [
    (margo_dir / "resources" / "icon.png", "application/vnd.margo.app.icon.v1+png", "resources/icon.png"),
    (margo_dir / "resources" / "license.txt", "application/vnd.margo.app.license.v1+plain", "resources/license.txt"),
    (margo_dir / "resources" / "release-notes.md", "application/vnd.margo.app.releaseNotes.v1+markdown", "resources/release-notes.md"),
    (margo_dir / "resources" / "description.md", "application/vnd.margo.app.descriptionFile.v1+markdown", "resources/description.md"),
]
```

Any file that isn't exactly one of those four names/extensions — a differently-named
icon, a non-`.png` icon, or any extra file a developer wants to ship — is never read,
never pushed, and nothing warns about it. There is also no validation today that a file
an `app.yaml` field *points to* actually exists before push.

**Bug 2 — remote `describe` fails on a valid, non-margot-authored manifest.** `margot
describe public.ecr.aws/g2n4p2m7/sensor-dashboard:1.9.1-margo-manifest` (an artifact
pushed by tooling other than margot, before margot existed) fails with:

```
Error: Artifact at ... is a Margo application descriptor but has no root app.yaml layer.
```

even though a correctly-typed descriptor layer (`mediaType:
application/vnd.margo.app.description.v1+yaml`) is present in the manifest — it is simply
not named `app.yaml`. The Margo spec's source of truth for "this is the descriptor layer"
is the layer `mediaType`, not any filename convention; margot invented the filename
requirement. `services/remote.py::resolve_remote_descriptor` and
`services/pull.py::_pull_recursive_components` both match on
`Path(path).name == "app.yaml"` instead of on `mediaType`.

Authoritative references: `.kiro/steering/oci-media-types.md` (media-type table, to be
extended), `.kiro/steering/code-conventions.md` (console output, imports), ROADMAP.md
Sprint 9 (remote describe/verify — the code this sprint fixes).

---

## 3. Authoritative Design

### Scope

**In scope:**
- `domain/layers.py` — new named media-type constants, replacing the string literals in
  `infra/oci.py`.
- `infra/oci.py::push_margo` — rewritten resource-file discovery: descriptor-field-driven
  for the four semantic slots (icon, descriptionFile, licenseFile, releaseNotes), plus a
  generic scan of `resources/` for anything else.
- `services/remote.py::resolve_remote_descriptor` — locate descriptor layer by `mediaType`.
- `services/pull.py::_pull_recursive_components` — same fix, same media type.
- Validation warning when an `app.yaml` field (`icon`, `descriptionFile`, `licenseFile`,
  `releaseNotes`) is set but the referenced file does not exist at push time.
- Validation warning when more than one layer in a pulled manifest has the descriptor
  media type (first match wins, all matches named in the warning).

**Not in scope:**
- `margot verify` schema changes (schema already allows arbitrary string paths for these
  fields — no LinkML change needed).
- `margot build`'s `copy_tree` — already copies `resources/` verbatim via
  `shutil.copytree`; not implicated by either bug. If investigation during implementation
  finds a real `build`-side gap, note it as a separate `fix:` and raise it, but do not
  expand this sprint's scope without flagging it back.
- `margot migrate` (deferred — see ROADMAP backlog, future sprint).
- Any change to `pull`'s default output contract (no `margo.yaml` synthesis — that is
  explicitly out of scope here and in Sprint 12).

### User-visible behavior

- `margot push`: any file referenced by `icon`/`descriptionFile`/`licenseFile`/
  `releaseNotes` in `app.yaml`, in any extension, is now pushed with a semantically
  correct media type matching that field and the file's real extension. Any other file
  found under `<margo_dir>/resources/` not referenced by one of those four fields is
  pushed too, with `artifactType`-adjacent fallback media type `application/octet-stream`
  and an OCI title annotation set to its path relative to the margo build dir (e.g.
  `resources/screenshot-1.png`).
- `margot push`: if `icon`/`descriptionFile`/`licenseFile`/`releaseNotes` is set in
  `app.yaml` but the referenced file is missing from the build output, `console.warning`
  is emitted (file is skipped, push continues — this is advisory, not a push-blocking
  error, consistent with resources today being optional).
- `margot describe`/`margot verify` (remote path) and `margot pull --recursive`: the
  descriptor layer is located by `mediaType ==
  application/vnd.margo.app.description.v1+yaml` regardless of filename. If more than one
  layer matches, `console.warning` lists all matching layers (digest + title annotation if
  present) and the first one (manifest layer order) is used.

### Contracts

**`domain/layers.py` — new constants** (alongside existing `COMPOSE_LAYER_MEDIA_TYPE` /
`QUADLET_LAYER_MEDIA_TYPE`):

```python
MARGO_DESCRIPTION_MEDIA_TYPE = "application/vnd.margo.app.description.v1+yaml"
MARGO_ICON_MEDIA_TYPE_TEMPLATE = "application/vnd.margo.app.icon.v1+{ext}"
MARGO_LICENSE_MEDIA_TYPE_TEMPLATE = "application/vnd.margo.app.license.v1+{ext}"
MARGO_RELEASE_NOTES_MEDIA_TYPE_TEMPLATE = "application/vnd.margo.app.releaseNotes.v1+{ext}"
MARGO_DESCRIPTION_FILE_MEDIA_TYPE_TEMPLATE = "application/vnd.margo.app.descriptionFile.v1+{ext}"
MARGO_RESOURCE_FALLBACK_MEDIA_TYPE = "application/octet-stream"
```

`{ext}` is the file's extension, lowercased, dot stripped (`.SVG` → `svg`, `.PNG` →
`png`). No allow-list — any extension is accepted and passed through generically
(`icon: resources/icon.bmp` → `application/vnd.margo.app.icon.v1+bmp`). A file with no
extension uses `bin` as `{ext}` (document this fallback explicitly in the function
docstring).

**`infra/oci.py::push_margo` — new resource resolution logic:**

Replace the hardcoded `optional` tuple list with a function (new, in `domain/` — pure,
testable, no I/O) that takes the parsed `app.yaml` dict and the margo build dir, and
returns the list of `(Path, media_type, annotation_title)` entries to push:

1. For each of the four fields (`icon`, `descriptionFile`, `licenseFile`,
   `releaseNotes`) present and non-empty in `app.yaml`'s top-level/`ApplicationMetadata`
   block: resolve the path relative to the margo build dir. If it exists, add
   `(resolved_path, TEMPLATE.format(ext=real_extension), relative_path_str)`. If it does
   not exist, `console.warning(f"'{field}' references '{value}' but the file was not
   found; skipping.")` — caller (an `infra`-layer function) emits the warning since
   `domain/` cannot import `console` (per `code-conventions.md` / `structure.md`
   layering); the pure function instead returns which fields were missing so `infra/`
   can warn.
2. Scan `<margo_dir>/resources/` (if it exists) for files not already matched by step 1
   (compare resolved absolute paths). For each: add `(path,
   MARGO_RESOURCE_FALLBACK_MEDIA_TYPE, f"resources/{path.name}")`.
3. Always keep `app.yaml` itself as the first, required entry (unchanged from today —
   `MARGO_DESCRIPTION_MEDIA_TYPE`).

Keep `domain/` pure (no `rich`, no `console`, no I/O side effects beyond `Path.exists()`
reads, which are acceptable I/O already used elsewhere in `domain/metadata.py` — confirm
against existing precedent before writing; if `domain/` purity rules in this codebase
disallow filesystem reads too, move the existence check into `infra/oci.py` instead and
keep `domain/` to pure string/path logic only). Resolve this during implementation by
checking how `domain/metadata.py::load_margo_yaml` already handles file I/O, and follow
the same precedent.

**`services/remote.py::resolve_remote_descriptor`:**

Replace:
```python
for path in pulled_paths:
    if Path(path).name == "app.yaml":
        app_yaml_path = path
        break
```
with manifest-layer-driven lookup: filter `prepared.manifest["layers"]` for `mediaType ==
MARGO_DESCRIPTION_MEDIA_TYPE`, map each matching layer's digest to its corresponding
pulled file path (pulled paths and manifest layers are in the same order from
`client.pull()` — confirm this ordering guarantee holds in `infra/oci.py` /
`services/pull.py` before relying on positional mapping; if not guaranteed, match via the
layer's title annotation → `resolve_filename` from `domain/layers.py`, which is already
how filenames are derived). If zero matches: existing error (reworded to mention
`mediaType` rather than filename). If more than one match: `console.warning` naming all
matches (title annotation or digest), proceed with the first.

**`services/pull.py::_pull_recursive_components`:** identical fix, same constant, same
first-match + warning-on-duplicate behavior. This function currently receives only
`root_paths` (plain path list) — it will need the manifest (or the matching layer list)
threaded through from its caller (`_handle_margo_artifact`) to do a mediaType-based
lookup; update the call chain accordingly.

### Dependencies

No new third-party dependencies. Pure refactor of existing OCI push/pull/resolve code
paths.

### Non-goals

- No `margo.yaml` synthesis from a pulled artifact (Sprint 12 / future `migrate`).
- No change to what `verify`/LinkML validates — these fields already accept arbitrary
  string paths.
- No UI/display changes to `describe`'s rendering of `icon`/`descriptionFile`/etc. (those
  already render the field value as a literal string per `rich-rendering.md`; unaffected).

---

## 4. Checkable Steps

- [ ] Add `MARGO_DESCRIPTION_MEDIA_TYPE` and the four `*_TEMPLATE` constants +
  `MARGO_RESOURCE_FALLBACK_MEDIA_TYPE` to `domain/layers.py`.
- [ ] Implement a pure resource-resolution function (new, in `domain/` or `infra/` per the
  purity precedent check above) that computes the push file-entry list from a parsed
  `app.yaml` dict + margo build dir path, per the algorithm in section 3.
- [ ] Rewrite `infra/oci.py::push_margo` to use the new resolution function instead of the
  hardcoded `optional` tuple list; thread through the missing-file warnings.
- [ ] Unit tests: icon as `.svg`, icon as no-extension file (`bin` fallback), an extra
  unreferenced `resources/` file (fallback media type + title annotation), a field
  pointing at a missing file (warning emitted, push continues without that file), and a
  regression test confirming the four original filenames (`icon.png`, `license.txt`,
  `release-notes.md`, `description.md`) still push with their original (now
  templated-but-equivalent) media types.
- [ ] Fix `services/remote.py::resolve_remote_descriptor` to key off
  `MARGO_DESCRIPTION_MEDIA_TYPE` instead of filename; add the duplicate-layer warning
  path.
- [ ] Fix `services/pull.py::_pull_recursive_components` (and its caller chain) the same
  way.
- [ ] Unit/integration tests: a fixture manifest whose descriptor layer is titled
  something other than `app.yaml` (e.g. `manifest.yaml`) resolves correctly in both
  `describe`'s remote path and `pull --recursive`; a fixture manifest with two
  description-media-type layers triggers the warning and picks the first.
- [ ] Update `.kiro/steering/oci-media-types.md` — add the templated icon/license/
  releaseNotes/descriptionFile media types and the `application/octet-stream` fallback to
  the "Margot-specific types" table.
- [ ] Update `docs/` (push command reference and/or concepts page) to document: resource
  files are discovered from `app.yaml` fields plus any extra file under `resources/`;
  extensions are passed through generically; missing referenced files warn rather than
  fail push.
- [ ] `make docs-check` passes.
- [ ] Each task committed as one or more commits (conventional-commit messages, e.g. `fix(push): ship resource files by app.yaml reference, not fixed filename`, `fix(describe): resolve descriptor layer by mediaType`).

---

## 5. Definition of Done

- [ ] All checkable steps completed.
- [ ] `make check` passes (lint + unit + integration tests).
- [ ] E2E test covering the originally reported SVG-icon case and the sensor-dashboard-style
  non-`app.yaml`-named descriptor case.
- [ ] Docs updated and `make docs-check` passes.
- [ ] No TODOs left (or explicitly deferred with a `# TODO(kiro): ...` comment and a
  ROADMAP backlog entry).
- [ ] Each task committed as one or more commits on the feature branch — no bulk
  end-of-sprint commit.
- [ ] Handed back for review (Gate 2). After approval the planner pushes; the owner opens
  the PR onto the release branch and merges. The agent does not push, open PRs, or manage
  worktrees.

---

## 6. Close-out Note

```
(filled in after merge)
```

---

## References

- [sprint-workflow skill](../skills/sprint-workflow/SKILL.md)
- [ROADMAP.md](../../ROADMAP.md)
- [oci-media-types.md](../steering/oci-media-types.md)
- [code-conventions.md](../steering/code-conventions.md)
- [structure.md](../steering/structure.md)
