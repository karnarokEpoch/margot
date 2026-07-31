---
name: fix-todos
description: >
  Locate, plan, and delegate fixes for # TODO(kiro): markers in the margot codebase.
  Use only when explicitly asked to find, review, or fix TODOs — not on every planning
  request.
---

# Fix TODOs Skill

## When to use

Only when the user explicitly asks to find, triage, or fix TODO markers. Do not run
this workflow proactively on unrelated planning or implementation requests.

## Workflow

1. Search for TODO markers:
   ```bash
   grep -rn "# TODO" --include="*.py" src/ tests/
   ```
   Any author tag counts (`TODO(kiro):`, `TODO(<other>):`, bare `TODO:`) — bare TODOs are
   a convention violation to flag, not to ignore (see `code-conventions.md`).
2. For each TODO found, read the surrounding function/class to understand what's
   actually required — the TODO text alone is often incomplete context.
3. **If a TODO is ambiguous, or its fix implies a design decision (API shape, new
   dependency, behavior change, breaking change), stop and ask the user before
   proceeding.** Do not guess intent and do not delegate a design decision to the dev
   agent — that decision is the user's to make, the same way sprint planning decisions
   in this repo are locked with the user first.
4. Group related, unambiguous TODOs (same file, same feature) into a single plan rather
   than one-off patches.
5. Build a short plan per group: what changes, which files, what test proves it's done.
6. Delegate implementation to the `python-dev` agent with the plan, file paths, and a
   definition of done: tests pass, the TODO marker is removed, changes are committed
   (conventional commit format).
7. Report back what was fixed and confirm no `# TODO` markers remain in the touched
   scope.

## Conventions this enforces

- Correct format is `# TODO(kiro): ...` (ruff TD002) — bare `# TODO:` must be fixed to
  include an author tag, not just left as-is.
- A TODO is not "done" until removed from source and its fix is committed — matching
  the sprint definition-of-done rule ("No `# TODO` markers left from this sprint's work").

## Scope

Source and test files only (`src/`, `tests/`). Do not treat TODO-shaped text inside
`.kiro/steering/*.md` or sprint docs as code TODOs to fix — those are conventions
references, not action items.
