# margot — Roadmap

Agile, vertical-slice roadmap. Each sprint ships one working, end-to-end capability
through all layers rather than building layers horizontally.

See [FEATURES.md](FEATURES.md) for the full spec and [TESTING.md](TESTING.md) for the
test plan. Where this roadmap diverges from FEATURES.md, this roadmap wins for
sequencing; FEATURES.md is updated as items land (see backlog).

---

## Sprint 1 — `fetch` a single OCI artifact (anonymous)

### Goal / Definition of Done

```
margot fetch public.ecr.aws/g2n4p2m7/belden-margo:1.0.1-victorialogs-margo-manifest
```

Fetches the OCI manifest for the given URI from an **anonymous-enabled** registry and
prints the **raw manifest JSON** to stdout. Green unit + E2E tests.

### Design decisions (locked)

- **Input:** a single positional OCI URI (`registry/repo:tag`). No flags for
  registry / repository / version. `fetch` inspects one final artifact, not a repo.
- **Output:** raw JSON (pretty-printed via rich). No table — tables are for listing
  many URIs, out of scope here.
- **Auth:** anonymous only. No login, no credentials, no ECR token.
- **No config file / dynaconf.** Not needed without auth or defaults.
- **No `publish_metadata.json`.** URI is fully caller-provided.
- **No SemVer gate on fetch.** Fetch reads/inspects arbitrary existing artifacts
  (incl. legacy `-margo-manifest` suffix tags). SemVer validation stays scoped to
  build/push per AGENTS.md.
- **No manifest validation.** Display whatever the registry returns. Recognizing /
  validating margo manifests is deferred (see backlog).

### Tasks (thin vertical slice)

| # | Task | Layer | Notes |
|---|------|-------|-------|
| 1 | Anonymous `get_manifest(uri) -> dict` wrapper around `oras.client.OrasClient` | `infra/oci.py` | Only boundary that touches the network. Mocked in tests. |
| 2 | Fetch orchestration: take URI → call infra → return manifest dict | `services/fetch.py` | No CLI, no rich. Pure orchestration. |
| 3 | `fetch` Typer command: positional `uri` arg → call service → pretty-print JSON | `commands/fetch.py` | Uses `rich` JSON rendering. |
| 4 | Register `fetch` command in Typer app | `src/margot/main.py` | Keep or drop `hello` smoke command. |
| 5 | Tests: service (mocked `OrasClient`) + E2E via `CliRunner` | `tests/` | Per TESTING.md. Assert manifest is fetched and printed. |

### Out of scope (explicit)

Auth / ECR, config file, `publish_metadata.json`, SemVer gate, manifest validation,
table output, other artifact types, `build` / `push` / `pull` / `verify`.

### Open / optional

- **URI parsing in `domain/`:** optional light reference validation (non-empty, has
  `:tag`) for a clean error on malformed input. Lean minimal — `oras` accepts the full
  target string. Add only if error UX needs it.

---

## Backlog / Stack (Sprint 2+)

Unordered within groups; sequencing decided at sprint planning.

### Auth (candidate Sprint 2)
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
- `build` (rsync + sed, variants, `.rsyncignore`)
- `push` (SemVer gate, media types, annotations)
- `pull`
- `verify` (LinkML: local + `--remote`)

### Cross-cutting
- `domain/tags.py` SemVer validation (required by build/push).
- `domain/metadata.py` `publish_metadata.json` parsing.
- `config.py` full dynaconf layering (flag > env > `margot.toml` > user config).
- ~~**Update FEATURES.md** `fetch` section: positional URI + raw JSON~~ ✓ done
