# Sprint 12 — Local descriptor fallback resolution (no `margo.yaml` required)

**Status:** in-flight
**Type:** feature
**Owner:** python-dev
**Release:** planned for `release/X.Y.Z` (TBD, after Sprint 11)

---

## 1. Goal

Let `margot describe` and `margot verify` run directly against a directory that has an
`app.yaml` (e.g. produced by `margot pull <margo-artifact> --output .`) but no
`margo.yaml` — silently, with no new flag.

---

## 2. Context

`margot pull` on a margo artifact writes its layers (typically `app.yaml` plus
`resources/*`) to the output directory, but no `margo.yaml`. Today, `margot describe` and
`margot verify` both resolve the descriptor via
`services/verify.py::resolve_descriptor`, which unconditionally calls
`load_margo_yaml(project_dir/margo.yaml)` first — there is no path that works without a
`margo.yaml` present locally. A user who just pulled an existing artifact to inspect it
cannot run `describe`/`verify` on it without hand-authoring a `margo.yaml`, which is
needless: `margo.yaml` only exists to (a) locate the source directory and (b) supply
Jinja2 rendering context for `app.yaml.jinja`. A bare, already-static `app.yaml` needs
neither.

This sprint intentionally does **not** change `pull`'s output contract (confirmed in
planning: pull stays a simple, predictable layer-dump — no synthesized files, no implicit
side effects) and does **not** implement manifest-to-`margo.yaml` reverse generation
(that is `margot migrate`, deferred — see ROADMAP backlog).

Authoritative references: Sprint 9 (remote describe/verify — introduced
`resolve_remote_descriptor`, which already has an equivalent fallback-free pattern for the
*remote* path, by construction, since it never touches `margo.yaml`), Sprint 11 (this
sprint depends on Sprint 11's `MARGO_DESCRIPTION_MEDIA_TYPE` constant only indirectly — no
hard dependency, can be sequenced either order, but land after 11 to avoid rebase
friction on `services/remote.py` neighbors).

---

## 3. Authoritative Design

### Scope

**In scope:**
- `services/verify.py::resolve_descriptor` — add a fallback path when `margo.yaml` is
  absent from `project_dir` and no explicit `manifest_path` was given.
- Fallback search order, tried in this exact sequence, first hit wins:
  1. `<project_dir>/app.yaml`
  2. `<project_dir>/margo/app.yaml`
- Fallback is **static-only** — no Jinja2 rendering attempted (`.jinja` variants are not
  searched in fallback mode; see rationale below).
- Error message update: when `margo.yaml` is absent *and* neither fallback path exists,
  the error names all paths that were tried.

**Not in scope:**
- No new CLI flag — the fallback is silent/automatic whenever `margo.yaml` is missing.
- No change to behavior when `margo.yaml` *is* present (existing path, including the
  `app.yaml` vs `app.yaml.jinja` mutual-exclusion check in `_find_descriptor`, is
  untouched).
- No `.jinja` fallback search — rationale: a template requires `margo.yaml`'s context to
  render (`build_jinja2_context(meta, ...)` takes a `MargoYaml`); without `margo.yaml`
  there is no context to render with, so finding a `.jinja` file in fallback mode can only
  ever dead-end. If a `.jinja` file is found at either fallback path with no `margo.yaml`
  present, raise the existing "no app.yaml or app.yaml.jinja found" style error rather
  than attempting a renderless read of a template file — do not silently return the raw
  unrendered template text as if it were valid YAML.
- No `pull`-side changes (confirmed: pull remains a simple layer dump).
- No `margot migrate` (separate future sprint).

### User-visible behavior

- `margot describe` / `margot verify` run from inside (or pointed at, via
  `--project-dir`) a plain pulled directory containing `app.yaml` at its root now succeed,
  with no `margo.yaml` and no new flags.
- Same for the documented default layout `margo/app.yaml` under `project_dir` (mirrors
  `margo.yaml`'s own default `directory: margo`, so a hand-copied partial project without
  a `margo.yaml` still resolves the same way a configured one would).
- When `margo.yaml` is present, behavior is byte-for-byte unchanged — this is purely an
  additive fallback for the absent case.
- `LoadedDescriptor.meta` is `None` for anything resolved via the fallback path (consistent
  with the existing `meta: MargoYaml | None` contract used for explicit `manifest_path`
  resolution today).

### Contracts

**`services/verify.py::resolve_descriptor`** — current shape:

```python
def resolve_descriptor(project_dir: str = ".", manifest_path: str | None = None) -> ResolvedDescriptor:
    meta: MargoYaml | None = None
    if manifest_path is not None:
        source = Path(manifest_path)
        if not source.is_file():
            raise ValueError(f"Application description not found: {manifest_path}")
    else:
        meta = load_margo_yaml(str(Path(project_dir) / "margo.yaml"))
        source = _find_descriptor(Path(project_dir) / meta.directory)
    ...
```

New shape — insert a fallback branch between the `manifest_path is not None` branch and
the `load_margo_yaml` call:

```python
    else:
        margo_yaml_path = Path(project_dir) / "margo.yaml"
        if margo_yaml_path.is_file():
            meta = load_margo_yaml(str(margo_yaml_path))
            source = _find_descriptor(Path(project_dir) / meta.directory)
        else:
            source = _find_descriptor_without_margo_yaml(Path(project_dir))
            # meta stays None
```

New helper, same module, same error-raising style as `_find_descriptor`:

```python
def _find_descriptor_without_margo_yaml(project_dir: Path) -> Path:
    """Locate a static app.yaml when no margo.yaml is present.

    Tries, in order: <project_dir>/app.yaml, <project_dir>/margo/app.yaml. Static only —
    a .jinja descriptor found at either path is an error, since rendering requires
    margo.yaml's context, which by definition is not available here.

    Raises:
        ValueError: If a .jinja descriptor is found instead of a static one, or if
            neither candidate path exists.
    """
```

Candidate paths each check for `app.yaml` (return immediately if found) and `app.yaml.jinja`
(raise immediately — do not fall through to the next candidate, since finding a `.jinja`
is a clear signal of "this needs margo.yaml", and silently skipping to the next path would
produce a confusing "not found" error instead of the actionable one). If neither candidate
directory has either file, raise with both tried paths listed.

`describe`'s own resolution (`services/describe.py::load_descriptor`) calls
`resolve_descriptor` already — no changes needed there beyond what flows through
automatically.

### Dependencies

None new.

### Non-goals

- `margot migrate` — explicitly deferred. Add to ROADMAP backlog with this scope note:
  generates a `margo.yaml` from an existing pulled/live manifest's `app.yaml` fields;
  default component↔variant mapping is 1:1 (one component becomes one variant); developer
  deduplicates manually afterward if multiple components should collapse to shared
  variants. Needs its own design pass before scheduling (read-from-pulled-dir vs.
  read-from-live-URI; which fields have no `margo.yaml` equivalent and are dropped vs.
  warned about; whether it also triggers a `pull` of resources).

---

## 4. Checkable Steps

- [ ] Implement `_find_descriptor_without_margo_yaml` in `services/verify.py` per the
  contract above.
- [ ] Wire the fallback branch into `resolve_descriptor`.
- [ ] Update the "not found" error message(s) to name both fallback paths that were tried.
- [ ] Unit tests: `app.yaml` at project root with no `margo.yaml` resolves; `margo/app.yaml`
  with no `margo.yaml` resolves (and takes priority correctly — root `app.yaml` wins over
  `margo/app.yaml` when both exist); a `.jinja` descriptor at either fallback path with no
  `margo.yaml` raises the actionable error (not silently rendered, not a generic
  not-found); neither path present raises with both paths named; existing `margo.yaml`
  present behavior is unchanged (regression test).
- [ ] Integration test: `margot pull <margo-artifact> --output <dir>` followed by `margot
  describe --project-dir <dir>` and `margot verify --project-dir <dir>` succeed with no
  `margo.yaml` written by `pull`.
- [ ] Add `migrate` scope note to `ROADMAP.md` backlog (see Non-goals above) — do not
  implement it.
- [ ] Update `docs/` (describe and verify command reference, and/or concepts page) to
  document the fallback search order and that it is silent/automatic.
- [ ] `make docs-check` passes.
- [ ] Each task committed as one or more commits (conventional-commit messages, e.g.
  `feat(verify): resolve app.yaml without margo.yaml via fallback search`).

---

## 5. Definition of Done

- [ ] All checkable steps completed.
- [ ] `make check` passes (lint + unit + integration tests).
- [ ] E2E test: pull a real/fixture margo artifact, then describe/verify it in place with
  no `margo.yaml`.
- [ ] Docs updated and `make docs-check` passes.
- [ ] No TODOs left (or explicitly deferred with a `# TODO(kiro): ...` comment and ROADMAP
  backlog entry — applies to the deferred `migrate` note).
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
- [sprint-11.md](./sprint-11.md) — related media-type/layer-discovery fixes, sequence after.
