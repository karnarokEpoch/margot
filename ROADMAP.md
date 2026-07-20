# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

---

## Sprint 3 — `build` package types locally

### Goal / Definition of Done

```
margot build --type all --version 1.3.0
margot build --type compose --variant all --version 1.3.0
```

Builds one or all package types into `build_dir` from local sources, performing
placeholder substitution. **Local only** — no registry, no network, no push, no auth.
Output: a populated `<build_dir>/<app_version>/` tree (rsynced margo dir + compose/quadlet
`.tgz` tarballs). Green unit + integration + E2E tests.

### Scope note

This is the **foundation sprint**: it introduces the whole `domain/` layer, `config.py`,
and `infra/filesystem.py` that `push` / `verify` will later reuse. Larger than sprints 1–2
by design; if it proves too big it can be split (domain + config foundation first, then the
`build` command), but the objective is a working end-to-end `build`.

### Design decisions (locked)

- **Signature (flag-based, per FEATURES.md):**
  `margot build [--type margo|compose|quadlet|all] [--version VERSION]
  [--registry REG] [--repository REPO] [--build-dir DIR] [--variant VARIANT]`.
  Unlike `fetch`/`pull` (URI-based), `build` is local and config-driven — it reads
  `publish_metadata.json` + config for defaults, with flag overrides.
- **SemVer gate (MANDATORY, per AGENTS.md).** Validate the version/tag with the SemVer
  regex **before any build step**. Reject non-SemVer immediately. Lives in `domain/tags.py`.
- **Config layering** (`config.py`, dynaconf): flag > `MARGOT_` env > `margot.yaml` >
  `~/.config/margot/config.yaml`. Keys: `registry`, `repository`, `build_dir`, `run_dir`.
  YAML (not TOML) for consistency with the rest of the margo ecosystem.
- **New dependency:** a YAML parser (PyYAML) is added to `pyproject.toml` for reading
  `publish_metadata.yaml` and the YAML config sources.
- **`publish_metadata.yaml`** is required for default versions; missing → clear, actionable
  error. YAML, consistent with `margo.yaml` / `compose.yaml` (replaces the old
  `publish_metadata.json`).
- **Local only.** No OCI manifest creation, no `artifactType`/annotations, no push, no auth,
  no network. Those are push concerns (Sprint 4+). `build` only produces the `build_dir` output.
- **Filesystem in pure Python — no host tooling.** Do **not** shell out to `rsync` / `sed` /
  `tar`. Reimplement the equivalent behavior with the standard library in `infra/filesystem.py`:
  - tree copy → `shutil.copytree` with an `ignore` callable + `symlinks`/`copy_function`
    handling (replaces `rsync -La`)
  - placeholder substitution → read → `str.replace` → write per text file (replaces `sed -i`)
  - archive → `tarfile` in `w:gz` mode (replaces `tar -czf`)
  Removes the host-binary dependency, is cross-platform, and is far easier to unit-test.
- **Variants:** `--variant NAME` explicit, or `--variant all` to scan source subdirs.
  compose variant = subdir containing `compose.yaml`; quadlet variant = subdir containing
  `.container` files.
- **`.rsyncignore`** (if present) parsed into ignore patterns and applied via the
  `shutil.copytree` `ignore` callable; symlinks handled by the copy's `symlinks` flag.
  (Filename kept for continuity with the old invoke tasks even though `rsync` is no longer used.)
- **Placeholder substitution** via in-Python text replacement (no `sed`): `<app_tag>`,
  `<compose_tag>`, `<quadlet_tag>`, `<helm_chart_tag>`, `<margo_tag>`, `<margo_version>`,
  plus registry/repository URLs.
- **Artifact-type suffixes removed.** No `-margo-manifest` / `-compose` / `-quadlet` in tags;
  type is a push-time `artifactType` concern.

### Tasks (thin vertical slice)

| # | Task | Layer | Notes |
|---|------|-------|-------|
| 1 | SemVer validation (`validate_tag` / `validate_version`) | `domain/tags.py` | Pure regex. MANDATORY gate. No mocks. |
| 2 | `publish_metadata.yaml` dataclasses + parser | `domain/metadata.py` | Pure. Unit-tested. |
| 3 | Extend `PackageType` (margo/compose/quadlet/all) + `BuildTarget` dataclass | `domain/models.py` | Reuse/extend the enum introduced in Sprint 2. Pure. |
| 4 | Dynaconf `Settings` with full layering | `config.py` | flag > env > `margot.toml` > user config. |
| 5 | Pure-Python file ops: tree copy with ignore (`.rsyncignore`), text placeholder substitution, gzip tar — `shutil` / `tarfile`, stdlib only | `infra/filesystem.py` | No host binaries. Unit-tested directly against temp dirs. |
| 6 | Build orchestration per type + variant loop for `all`/`--variant all` | `services/build.py` | read metadata → validate SemVer → rsync → sed → (tar for compose/quadlet). |
| 7 | `build` Typer command with flags → call service → report outputs | `commands/build.py` | rich output of produced paths. |
| 8 | Register `build` in the Typer app | `main.py` | |
| 9 | Tests: domain unit (tags/metadata/models, no mocks), service integration (mock filesystem), E2E via `CliRunner` | `tests/` | Per TESTING.md. |
| 10 | Update FEATURES.md `build` section as behavior lands | `FEATURES.md` | Closes backlog items. |

### Out of scope (explicit → Sprint 4+)

`push` (OCI manifest creation, media types, annotations, SemVer-gated push), `login` /
`logout` / auth / ECR, `verify` (LinkML), display UX, manifest recognition/validation.

### Open / needs a decision

- **Variant tag format.** FEATURES.md marks this TBD ("`1.3.0`, `1.3.0-simple.1`,
  `1.3.0+addon-mosquitto` — exact format TBD by project convention"). The tool will validate
  *any* SemVer tag; the **convention** for encoding a variant into that tag needs a decision
  before variant builds are meaningful. Flag for sprint planning.

---

## Backlog / Stack (Sprint 4+)

Unordered within groups; sequencing decided at sprint planning.

### Auth (candidate Sprint 4)
- `margot login` / `logout` — `services/auth.py`
- Credentials file R/W — `infra/credentials.py`
- ECR token fetch (boto3) — `infra/ecr.py`
- Credential expiry check before every registry op
- Authenticated `fetch` against private ECR

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
- `push` (SemVer gate, media types, annotations)
- `verify` (LinkML: local + `--remote`)

### Cross-cutting
- `domain/tags.py` SemVer validation (required by build/push). → **scheduled Sprint 3**
- `domain/metadata.py` `publish_metadata.json` parsing. → **scheduled Sprint 3**
- `config.py` full dynaconf layering (flag > env > `margot.toml` > user config). → **scheduled Sprint 3**
- ~~**Update FEATURES.md** `fetch` section: positional URI + raw JSON~~ ✓ done

---

## Completed Sprints

| Sprint | Capability | Release |
|--------|-----------|---------|
| Sprint 1 | `margot fetch` — anonymous OCI manifest retrieval, pretty-printed JSON output, URI validation, `margot --version` | [0.1.0](https://github.com/karnarokEpoch/margot/releases/tag/0.1.0) |
| Sprint 2 | `margot pull` — anonymous OCI artifact pull to disk, artifact type detection via `artifactType`, layer naming (title annotation → manifest-level fallback), `--force` override for unknown types, shared `domain/uri.py` | — |
