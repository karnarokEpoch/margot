# margot — Agent Guide

margot is a Python developer CLI for building, publishing, validating, and inspecting Margo application packages as OCI
artifacts. Its source follows a layered architecture: `commands/` → `services/` → `domain/` and `infra/`; `domain/`
stays pure.

## Start here

- [Product context](.kiro/steering/product.md) — purpose, users, and current surface.
- [Structure context](.kiro/steering/structure.md) — repository map and placement rules.
- [Technology context](.kiro/steering/tech.md) — runtime, commands, constraints, and releases.
- [FEATURES.md](FEATURES.md) — authoritative behavior, architecture, configuration, and OCI media types.
- [TESTING.md](TESTING.md) — test strategy and coverage requirements.
- [ROADMAP.md](ROADMAP.md) — accepted delivery sequence and planned work.

Read the context relevant to the task; `FEATURES.md` wins over user documentation when behavior disagrees.

## Route work to the right agent

- **`planner`** (`.kiro/agents/planner.json`) — investigate, settle design, record a checkable plan, and delegate
  implementation. It does not edit source or tests.
- **`python-dev`** (`.kiro/agents/python-dev.json`) — implement Python behavior and tests after the design is approved.
- **`docs-writer`** (`.kiro/agents/docs-writer.json`) — maintain only the MkDocs site under `docs/` and its navigation;
  it does not modify Python source.

Select or delegate to the named agent according to task scope. Keep product decisions with the planner, implementation
with `python-dev`, and public-site changes with `docs-writer`.

## Use local skills on demand

- **`code-quality-enhancement`** (`.kiro/skills/code-quality-enhancement/SKILL.md`) — use only for explicitly requested
  Ruff, coverage, or import-style improvement.
- **`fix-todos`** (`.kiro/skills/fix-todos/SKILL.md`) — use only for explicitly requested TODO discovery, triage, or
  fixes.

## Detailed steering

- `code-conventions.md` — imports, TDD, terminal output, TODO format, and third-party inheritance rules.
- `rich-rendering.md` — safe and faithful rendering of externally supplied data.
- `oci-media-types.md` — canonical OCI and Docker media-type constants.
- `documentation.md` — MkDocs authority, style, and verification rules.

These files own detailed procedures. Do not duplicate them here; update their source of truth when policy changes.
