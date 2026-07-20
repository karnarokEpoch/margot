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
Output: a populated `<build_dir>/<version>/` tree (copied margo dir + compose/quadlet
`.tgz` tarballs). Green unit + integration + E2E tests.

### Scope note

This is the **foundation sprint**: it introduces the whole `domain/` layer, `config.py`,
and `infra/filesystem.py` that `push` / `verify` will later reuse. Larger than sprints 1–2
by design; if it proves too big it can be split (domain + config foundation first, then the
`build` command), but the objective is a working end-to-end `build`.

### Design decisions (locked)

- **Project descriptor: `margo.yaml` at project root.** Single source of truth for all
  component versions, directories, repositories, app metadata (name, description,
  annotations, maintainers). Replaces `publish_metadata.json`. Read by `margot build`
  and `margot push`. Missing → clear error (exit 1).
- **`app.yaml` inside the margo source directory.** The Margo app descriptor (previously
  named `margo.yaml` inside the `margo/` dir) is now `app.yaml`. Contains placeholders
  (`<compose_tag>`, `<quadlet_tag>`, etc.) that `margot build` substitutes with values
  from the root `margo.yaml`.
- **Signature (flag-based, per FEATURES.md):**
  `margot build [--type margo|compose|quadlet|all] [--version VERSION]
  [--registry REG] [--repository REPO] [--build-dir DIR] [--variant VARIANT]`.
  Unlike `fetch`/`pull` (URI-based), `build` is local and config-driven — it reads
  `margo.yaml` + config for defaults, with flag overrides.
- **OCI tag validation gate (MANDATORY, per AGENTS.md).** Validate every tag before any
  build step. Valid OCI tags: `[a-zA-Z0-9_.-]+`. `_` encodes `+` (SemVer build metadata
  separator) per the Margo OCI distribution spec. Tags are normalized (`_`→`+`) for
  SemVer semantic validation but stored as-is with `_`. Lives in `domain/tags.py`.
- **Variant tag format (RESOLVED).** `<version>_<variant>` — e.g. `1.3.0_simple`,
  `1.3.0_addon-mosquitto`. The `_` encodes `+` (build metadata) per the Margo OCI spec.
  Variants are declared explicitly in `margo.yaml` under each component's `variants` list
  with their own `name` and `version` fields. `--variant all` expands the full variants
  list; `--variant NAME` selects one entry by name. Discovery of variants on disk is not
  used — the `margo.yaml` declaration is authoritative. All variant names (including
  `default`) map to `<component.directory>/<name>/` — there is no implicit root mapping.
- **Config layering** (`config.py`, dynaconf): flag > `MARGOT_` env > `margot.yaml` >
  `~/.config/margot/config.yaml`. Keys: `registry`, `repository`, `build_dir`, `run_dir`.
  YAML for consistency with the rest of the margo ecosystem.
- **New dependency:** PyYAML added to `pyproject.toml` for reading `margo.yaml`.
- **Local only.** No OCI manifest creation, no `artifactType`/annotations, no push, no auth,
  no network. Those are push concerns (Sprint 4+). `build` only produces the `build_dir` output.
- **Filesystem in pure Python — no host tooling.** Do **not** shell out to `rsync` / `sed` /
  `tar`. Use stdlib in `infra/filesystem.py`:
  - tree copy → `shutil.copytree` with ignore callable (`.rsyncignore` patterns)
  - placeholder substitution → read → `str.replace` → write per text file
  - archive → `tarfile` in `w:gz` mode
- **Tarball contents.** For compose/quadlet, the tarball contains the flat contents of the
  source dir (or variant subdir) — not the dir itself as root. Output filename:
  `<name>-<version>.tgz` where `name` is from `margo.yaml` root and `version` is the
  component (or variant) version.
- **Placeholder substitution** is applied only to `app.yaml` for the margo type. For
  compose/quadlet, substitution is applied to all text files in the source tree.
  Placeholders: `<app_tag>`, `<compose_tag>`, `<quadlet_tag>`, `<helm_chart_tag>`,
  `<margo_tag>`, `<margo_version>`. Values sourced from component versions in `margo.yaml`.
- **Artifact-type suffixes removed.** No `-margo-manifest` / `-compose` / `-quadlet` in tags.

### Tasks (thin vertical slice)

| # | Task | Layer | Notes |
|---|------|-------|-------|
| 1 | OCI tag + SemVer validation (`validate_oci_tag`, `validate_semver`) | `domain/tags.py` | Pure. `_`→`+` normalization before SemVer parse. MANDATORY gate. No mocks. |
| 2 | `margo.yaml` dataclasses + parser | `domain/metadata.py` | `MargoYaml`, `ComponentConfig`, `VariantConfig` dataclasses. Pure. Unit-tested. |
| 3 | Extend `PackageType` with `ALL` + `BuildTarget` dataclass | `domain/models.py` | Reuse/extend enum from Sprint 2. Pure. |
| 4 | Dynaconf `Settings` with full layering | `config.py` | flag > env > `margot.yaml` > user config. |
| 5 | Pure-Python file ops: tree copy with ignore, placeholder substitution, gzip tar | `infra/filesystem.py` | No host binaries. Unit-tested against temp dirs. |
| 6 | Build orchestration per type + variant loop | `services/build.py` | read `margo.yaml` → validate tag → copy → substitute → (tar for compose/quadlet). |
| 7 | `build` Typer command with flags → call service → report outputs | `commands/build.py` | rich output of produced paths. |
| 8 | Register `build` in the Typer app | `main.py` | |
| 9 | Tests: domain unit (tags/metadata/models, no mocks), service integration (mock filesystem), E2E via `CliRunner` | `tests/` | Per TESTING.md. |
| 10 | Update FEATURES.md `build` section as behavior lands | `FEATURES.md` | Closes backlog items. |

### Out of scope (explicit → Sprint 4+)

`push` (OCI manifest creation, media types, annotations, SemVer-gated push), `login` /
`logout` / auth / ECR, `verify` (LinkML), display UX, manifest recognition/validation.

### Open / needs a decision

~~**Variant tag format.**~~ ✓ Resolved: `<version>_<variant>` (e.g. `1.3.0_simple`).
`_` encodes `+` per Margo OCI spec. Declared in `margo.yaml` variants list.

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
- `domain/tags.py` OCI tag + SemVer validation. → **scheduled Sprint 3**
- `domain/metadata.py` `margo.yaml` project descriptor parsing. → **scheduled Sprint 3**
- `config.py` full dynaconf layering (flag > env > `margot.yaml` > user config). → **scheduled Sprint 3**
- ~~**Update FEATURES.md** `fetch` section: positional URI + raw JSON~~ ✓ done

---

## Completed Sprints

| Sprint | Capability | Release |
|--------|-----------|---------|
| Sprint 1 | `margot fetch` — anonymous OCI manifest retrieval, pretty-printed JSON output, URI validation, `margot --version` | [0.1.0](https://github.com/karnarokEpoch/margot/releases/tag/0.1.0) |
| Sprint 2 | `margot pull` — anonymous OCI artifact pull to disk, artifact type detection via `artifactType`, layer naming (title annotation → manifest-level fallback), `--force` override for unknown types, shared `domain/uri.py` | — |
