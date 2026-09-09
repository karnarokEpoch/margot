---
inclusion: auto
description: >
  Runtime, toolchain, validation commands, technical constraints, and release workflow
  for margot.
---

<!-- markdownlint-disable-file MD041 -->

# Technology Context

## Runtime and stack

- Python 3.12 or newer; dependencies and virtual environments are managed with `uv`.
- Typer provides the CLI, Rich provides terminal rendering, dynaconf supplies layered configuration, oras-py performs
  OCI registry operations, and LinkML validates Margo application descriptions.
- Use `uv sync` for setup and invoke project tools through `uv run` or Make targets.

## Standard checks

- `make test` — pytest with the required coverage threshold.
- `make lint` — Ruff checks for `src/` and `tests/` without auto-fixing.
- `make check` — lint followed by tests.
- `make docs-check` — strict MkDocs build after public documentation changes.

## Technical constraints

Use the layered dependency direction defined in `structure.md`. OCI operations go through oras-py, not an ORAS CLI
subprocess. Build and push validate tags before work begins; artifact type belongs in OCI metadata, not tag suffixes.
Registry calls perform the credential-expiry check first.

Detailed implementation conventions belong to `code-conventions.md`, display safety to `rich-rendering.md`, OCI
media-type values to `oci-media-types.md`, and documentation rules to `documentation.md`.

## Release workflow

Versioning comes from git tags through Hatch VCS. Release changes use a `release/<version>` branch and PR; merging it to
`main` triggers the release workflow to create the tag, build artifacts, generate notes, and publish the GitHub release.
Do not create or push release tags manually. `CONTRIBUTING.md` owns the complete process.
