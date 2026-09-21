---
inclusion: manual
---

# Documentation Conventions

Rules for writing and maintaining the MkDocs site under `docs/`.

## Authority model

- **`docs/`** (MkDocs) is the **standing source of truth for shipped behavior**. Anything that has
  been released is documented here — command contracts, flag tables, exit codes, error messages,
  `margo.yaml` field rules, OCI media types, config layering.
- **`.kiro/sprints/sprint-N.md`** is **authoritative for in-flight design** — what the dev agent
  implements against and what "done" is judged by. It is deleted on sprint close-out; git history
  is the archive.
- **`ROADMAP.md`** is the **forward register** — upcoming features, fixes, ideas, and backlog. A
  queue of intent, not a spec.

When a doc page and `docs/` disagree with a sprint file, the sprint file governs behavior not yet
shipped; the docs page governs everything that has shipped. After a sprint closes, docs must be
updated to reflect the shipped behavior.

New user-facing behavior: write the sprint design in `.kiro/sprints/sprint-N.md` first; update
`docs/` as part of the sprint close-out (before or at merge).

`.kiro/steering/oci-media-types.md` governs OCI media-type strings — use it for any code samples
in docs (e.g. media type strings, CLI output). Don't invent conventions the code doesn't follow.

## Audience

Two audiences — don't blend them in the same page:

- **Users** (platform engineers, app developers packaging with margot) — task-oriented:
  install, configure, build, push, pull. Landing page and command reference target this
  audience.
- **Contributors** — architecture, layering (`commands/` → `services/` → `domain/`+`infra/`),
  testing strategy. Link to `AGENTS.md` / `TESTING.md` rather than duplicating them. No
  `docs/architecture.md` — contributor content stays in `.kiro/steering/`.

## Style

- Concise, actionable, high-signal. No filler, no marketing language.
- Lead with the command or config snippet, then explain if needed — not the reverse.
- One canonical OCI URI example everywhere: `public.ecr.aws/g2n4p2m7/margo:1.0.0`
  (see `code-conventions.md`). Never project- or customer-specific refs.
- Code/config samples must be copy-pasteable and runnable as shown — no pseudo-code.
- Use admonitions (`!!! note`, `!!! warning`) sparingly, only for things that would
  otherwise cause a mistake.

## Structure

The docs site layout is:

```
docs/
  index.md              # landing page
  margo-yaml.md         # project descriptor reference
  config.md             # config layering + margot.toml
  concepts.md           # package types, tags, media types, project layout
  commands/
    build.md  push.md  pull.md  fetch.md  verify.md  describe.md  auth.md
  examples/ ...
```

One page per command under `docs/commands/`. Each command page carries the full contract:
synopsis, flag table, behavior description, exit codes, and runnable examples.

Navigation is declared explicitly in `mkdocs.yml` (`nav:`) — don't rely on directory
auto-discovery. Adding a new page requires a nav entry.

No `docs/architecture.md` — contributor and layering content stays in
`.kiro/steering/structure.md` and `.kiro/steering/tech.md`.

## Build verification

- `make docs-check` (strict build, warnings as errors) must pass before any doc change is
  considered done. Broken internal links or nav entries are build failures, not warnings
  to ignore.
