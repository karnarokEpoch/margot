# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

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

## Completed Sprints

| Sprint | Capability | Release |
|--------|-----------|---------|
| Sprint 1 | `margot fetch` — anonymous OCI manifest retrieval, pretty-printed JSON output, URI validation, `margot --version` | [0.1.0](https://github.com/karnarokEpoch/margot/releases/tag/0.1.0) |
| Sprint 2 | `margot pull` — anonymous OCI artifact pull to disk, artifact type detection via `artifactType`, layer naming (title annotation → manifest-level fallback), `--force` override for unknown types, shared `domain/uri.py` | — |
| Sprint 3 | `margot build` — local artifact build for margo/compose/quadlet package types, placeholder substitution (`<app_tag>` from `appVersion`, `<margo_tag>`, `<compose_tag>`, `<quadlet_tag>`), variant support, idempotent output dir, multi-type `-t` flag, `margo.yaml` project descriptor, dynaconf config layering, pure-Python filesystem ops | — |
