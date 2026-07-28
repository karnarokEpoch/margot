---
inclusion: manual
---

# Documentation Conventions

Rules for writing and maintaining the MkDocs site under `docs/`.

## Source of truth

- [`FEATURES.md`](../../FEATURES.md) is authoritative for behavior, architecture, commands,
  config, and OCI media types. Docs must never contradict it.
- If a doc page and `FEATURES.md` disagree, `FEATURES.md` wins — fix the doc.
- New user-facing behavior lands in `FEATURES.md` first (or alongside). Docs follow, they
  don't lead.
- [`.kiro/steering/oci-media-types.md`](oci-media-types.md) apply to any code samples shown
  in docs (e.g. media type strings, CLI output style). Don't invent conventions the code
  doesn't follow.

## Audience

Two audiences, don't blend them in the same page:

- **Users** (platform engineers, app developers packaging with margot) — task-oriented:
  install, configure, build, push, pull. Landing page and command reference target this
  audience.
- **Contributors** — architecture, layering (`commands/` → `services/` → `domain/`+`infra/`),
  testing strategy. Link to `AGENTS.md` / `TESTING.md` rather than duplicating them.

## Style

- Concise, actionable, high-signal. No filler, no marketing language.
- Lead with the command or config snippet, then explain if needed — not the reverse.
- One canonical OCI URI example everywhere: `public.ecr.aws/g2n4p2m7/margo:1.0.0`
  (see `code-conventions.md`). Never project- or customer-specific refs.
- Code/config samples must be copy-pasteable and runnable as shown — no pseudo-code.
- Use admonitions (`!!! note`, `!!! warning`) sparingly, only for things that would
  otherwise cause a mistake.

## Structure

- `docs/index.md` — landing page: what margot is, quick install, links out. Keep it short.
- One page per concern once content grows (commands, `margo.yaml` reference, config,
  architecture) — don't grow `index.md` into a monolith.
- Navigation is declared explicitly in `mkdocs.yml` (`nav:`) — don't rely on directory
  auto-discovery.

## Build verification

- `make docs-check` (strict build, warnings as errors) must pass before any doc change is
  considered done. Broken internal links or nav entries are build failures, not warnings
  to ignore.
