# Fix — variant version build metadata is derived from the component name

**Status:** planned
**Type:** fix, breaking default (no sprint number; lands on its own branch in any release, see `sprint-workflow`)
**Owner:** python-dev (code and tests), docs-writer (docs under `docs/`)
**Release:** `release/0.13.0` or later (TBD by the owner)

---

## 1. Goal

When a variant omits `version`, build its semver build metadata (the part after `+`) from the variant's
`component` name, so the OCI tag, the `.dist/<tag>/` folder and the Margo component name in the
deployment profile all use the same identifier.

---

## 2. Context

Reported while working on `/home/louis/work/margo/apps_margo/bhdo`, whose `margo.yaml` has:

```yaml
quadlet:
  version: 1.1.3
  variants:
    - name: with-bis
      component: bhdo-quadlet-with-bis
```

Today the same artifact has two names:

| Where | Value |
|---|---|
| `deploymentProfiles[].components[].name` (from `variant.component`) | `bhdo-quadlet-with-bis` |
| `deploymentProfiles[].components[].properties.revision` (from `variant.tag`) | `1.1.3_quadlet-with-bis` |

Cause: the default variant version is `f"{component.version}+{component_type}-{variant.name}"`, which
ignores `variant.component`. `variant.component` is only exposed to templates (`{{ v.component }}`); it
never reaches the version, tag, build folder or archive.

The same f-string is hardcoded in four places, which is why nobody noticed the drift:

| File | Function |
|---|---|
| `src/margot/domain/metadata.py` | `_build_component_context` (template context) |
| `src/margot/services/build.py` | `_build_variant_component` |
| `src/margot/services/push.py` | `_push_variant_component` (variant branch) |
| `src/margot/services/package.py` | `_resolve_component_versions` |

Authoritative references: `docs/templating.md`, `docs/margo-yaml.md` (Variants), `docs/concepts.md`
(tag table), `.kiro/steering/code-conventions.md` (exit codes, imports, console rules).

---

## 3. Authoritative Design

### Scope

**In scope:**

- One pure function in `domain/metadata.py` that resolves a variant's component name and version. The four
  sites above call it; no site keeps its own f-string.
- Tests, and docs for the new rule.

**Not in scope:** see Non-goals.

### Behavior

| Case | Before | After |
|---|---|---|
| Variant with authored `version` | used as written | unchanged |
| Variant without `version` | `<component.version>+<type>-<variant.name>` | `<component.version>+<variant.component>` |
| Variant without `component` | `component` = `<id>-<type>-<variant.name>` | unchanged (and now also feeds the version) |
| Flat layout (no variants) | `<version>`, `component` = `<id>-<type>` | unchanged |

The OCI tag is the version with `+` replaced by `_`, as today.

Example (bhdo): `quadlet.version: 1.1.3`, variant `with-bis`, `component: bhdo-quadlet-with-bis`:

- version `1.1.3+bhdo-quadlet-with-bis`
- tag and `revision` `1.1.3_bhdo-quadlet-with-bis`
- `.dist/1.1.3_bhdo-quadlet-with-bis/<name>-1.1.3_bhdo-quadlet-with-bis.tgz`
- No change needed in the bhdo `margo.yaml` or `app.yaml.jinja`.

Example without `component` (`id: com-example-nginx`, compose variant `default`, `version: 2.1.0`):

- component `com-example-nginx-compose-default`
- version `2.1.0+com-example-nginx-compose-default`, tag `2.1.0_com-example-nginx-compose-default`

### Contracts

`domain/metadata.py`: add a pure function, for example `resolve_variant(meta_id, component_type, component_version,
variant) -> tuple[str, str]` returning `(component_name, version)`. Name and shape are the dev agent's choice,
but it must:

- return the authored `variant.version` unchanged when present;
- return `variant.component` when present, else `<id>-<type>-<variant.name>`;
- derive the default version as `f"{component_version}+{component_name}"`;
- raise `ValueError` when the version is needed but `component_version` is `None` (callers keep their
  current error messages, for example `quadlet base version is required when variant 'x' omits version`);
- have no I/O and no `rich` or `console` import (`domain/` stays pure).

Callers keep their existing validation order: replace `+` with `_`, then `validate_oci_tag` and
`validate_semver`. A component name that yields an invalid tag or semver (characters outside the
semver build-metadata set, or a tag over 128 characters) fails with a `ValueError`, exit **3**. The dev
agent verifies how `validate_semver` treats the `_` form and keeps the error message naming the
component.

`build.py`, `push.py`, `package.py` and `metadata.py` all use `meta.id` plus the helper. `package.py`
has no `meta` today; pass the id in.

### Dependencies

None new.

### Non-goals

- No change to authored `version` handling, flat layout, `repository`, or `image`.
- No new `margo.yaml` field and no opt-out flag. Authoring `version` per variant is the escape hatch for
  anyone who needs the old tag.
- No migration command. The break is documented, not automated.
- No change to the default component name (`<id>-<type>-<variant.name>`).
- Not covered here (decide separately if wanted): a `manifest.<type>.components` template helper to
  avoid retyping component names in `parameters[].targets[].components`.

### Decisions assumed (owner to confirm before work starts)

1. **Breaking default accepted.** Projects with variants and no authored `version` get new tags and must
   re-push; anything pinning the old tags breaks.
2. **Long default kept.** The default component name keeps the `<id>-` prefix, so default metadata is long
   for projects that do not author `component`.
3. **No sprint number.** Handled as a fix (precedent: `fix-auth-login-password.md`).

---

## 4. Checkable Steps

Tests first (TDD). Exit-code tests follow `…_exits_<code>` with matching docstrings.

- [ ] Unit tests for the new helper in `tests/unit/` (domain): authored `version` wins; unauthored uses
  `+<component>`; authored `component` wins over the default name; default component name when absent;
  missing `component_version` raises `ValueError`.
- [ ] Unit tests for `build_jinja2_context`: variant `version`, `tag`, `ref` and `component` are consistent
  (`tag` ends with the `component`) for authored and default component names, compose and quadlet.
- [ ] Update existing tests that assert the old form: `tests/unit/test_services_package.py`
  (`…_quadlet-prod`, `…_quadlet-dev`) and any build, push or template test with `+<type>-<variant>`;
  grep `tests/` for `compose-` and `quadlet-` tag literals.
- [ ] Test that `build`, `push --dry-run` and `package` yield the same tag for the same variant.
- [ ] Test an invalid component name (for example one containing `.` or `_` if rejected, or an over-long
  name): exits 3, message names the component.
- [ ] Implement the helper and replace the four f-strings with calls to it.
- [ ] `make check` passes.
- [ ] Docs (`docs-writer`): update the derivation text and tables in `docs/margo-yaml.md` (Variants,
  tag table), `docs/concepts.md` (tag table), `docs/templating.md` (variant fields table and rendered
  examples), `docs/examples/full.md` (derived-version table and rendered values) and
  `docs/commands/push.md` (example output). State the rule once: metadata follows `component`. Add a
  breaking-change note with the `version:` escape hatch. Check `README.md` and `CONTRIBUTING.md` for the old form.
- [ ] `make docs-check` passes.
- [ ] Manual check in `/home/louis/work/margo/apps_margo/bhdo`: `margot build` writes
  `.dist/1.1.3_bhdo-quadlet-default/` and `.dist/1.1.3_bhdo-quadlet-with-bis/`, the rendered `app.yaml`
  `revision` values match them, and `margot verify` passes.
- [ ] Close-out, after the above passes: delete this file in its own commit
  `chore: close out fix variant-version-from-component`, remove the ROADMAP backlog entry, and check that
  no reference to `fix-variant-version-from-component` is left in `*.md` files.
- [ ] Each task committed as one or more commits (for example
  `test(variants): …`, `fix(variants)!: derive variant build metadata from component name`,
  `docs(variants): …`).

---

## 5. Definition of Done

- [ ] All checkable steps completed.
- [ ] `make check` passes (lint and tests with the coverage threshold).
- [ ] Docs updated and `make docs-check` passes.
- [ ] No TODOs left (or explicitly deferred with a `# TODO(kiro): …` comment and a ROADMAP backlog entry).
- [ ] Each task committed as one or more commits on the feature branch, no bulk end-of-work commit. The
  breaking change is marked with `!` in the commit type.
- [ ] Handed back for review (Gate 2). After approval the planner pushes; the owner opens the PR onto the
  release branch and merges. The agent does not push, open PRs, or manage worktrees.

---

## 6. Close-out Note

```text
(filled in after merge)
```

---

## References

- [sprint-workflow skill](../skills/sprint-workflow/SKILL.md) — fixes need no sprint number.
- [ROADMAP.md](../../ROADMAP.md)
- [code-conventions.md](../steering/code-conventions.md)
- [docs/templating.md](../../docs/templating.md)
- [docs/margo-yaml.md](../../docs/margo-yaml.md)
