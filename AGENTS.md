# AGENTS.md — margot

Guidance for AI agents working in this repo.

## Key files

- [`FEATURES.md`](FEATURES.md) — authoritative spec: commands, architecture, OCI media types, config, error handling.
- [`TESTING.md`](TESTING.md) — test structure, stack, priorities, coverage requirements.

Read both before touching anything.

## Architecture

Strict layered architecture: `commands/` → `services/` → `domain/` + `infra/`.
Inner layers never import outer ones. `domain/` is pure Python — no I/O, no frameworks.
See the layer table and project structure in `FEATURES.md`.

## Non-negotiables

- All tags must be valid SemVer. Validate before any build/push. See `domain/tags.py`.
- OCI operations go through `oras-py` only — no subprocess calls to the ORAS CLI.
- Credential expiry check runs before every registry operation.
- Artifact type is encoded in `artifactType`, never in the tag string.

## Testing

- Write unit tests for `domain/` first (no mocks needed).
- Mock `OrasClient` at the `infra/oci.py` boundary — never hit a live registry.
- E2E via Typer `CliRunner`. See `TESTING.md` for full structure.

## Running tests

```bash
uv run pytest
```

Coverage report prints automatically (`--cov=margot --cov-report=term-missing`).
