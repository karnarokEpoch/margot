---
inclusion: auto
description: >
  Repository layout, source-layer locations, and file-organisation rules for margot.
---

<!-- markdownlint-disable-file MD041 -->

# Structure Context

## Repository map

- `src/margot/` — installed package.
  - `commands/` parses CLI input and renders output.
  - `services/` orchestrates feature flows.
  - `domain/` contains pure models and logic.
  - `infra/` owns filesystem, registry, credentials, and templating I/O.
  - `validation/` contains LinkML-specific adapters.
  - `schemas/` holds vendored schema data.
- `tests/unit/`, `tests/integration/`, `tests/e2e/` — tests by scope; shared fixtures live under `tests/fixtures/`.
- `docs/` and `mkdocs.yml` — public MkDocs site.
- `.kiro/agents/`, `.kiro/skills/`, `.kiro/steering/`, and `.kiro/sprints/` — local agent configuration, on-demand
  procedures, persistent guidance, and approved plans.
- `FEATURES.md`, `TESTING.md`, `ROADMAP.md`, and `CONTRIBUTING.md` — product spec, test strategy, delivery plan, and
  contributor workflow.

## Organisation rules

Dependencies point inward: `commands` → `services` → `domain` and `infra`. `domain` has no I/O or framework imports;
`validation` returns data rather than terminal renderables. Keep tests aligned to their matching scope and place user
documentation in `docs/`, not in source comments.

`FEATURES.md` owns the detailed architecture and layer-responsibility table. See `tech.md` for runtime and validation
commands; see `code-conventions.md` for detailed code rules.
