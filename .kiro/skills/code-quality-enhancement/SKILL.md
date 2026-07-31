---
name: code-quality-enhancement
description: >
  Find and fix code quality regressions in margot: ruff lint violations, low test
  coverage, and global (non-selective) imports. Use when asked to improve code
  quality, clean up lint, raise coverage, or fix import style — not on every
  request.
---

# Code Quality Enhancement Skill

Three independent triggers, each with its own workflow. Run only the one(s) the
user asked for — do not run all three unless explicitly asked to do a full pass.

## When to use

Only when explicitly asked to improve code quality, fix lint, raise test coverage, or
fix import style. Do not run proactively during unrelated feature or bugfix work.

## Trigger 1 — ruff lint

1. Run `make lint` (`ruff check --no-fix src/ tests/`) and capture the full output.
2. Read each flagged file's surrounding context — not just the flagged line — before
   deciding on a fix.
3. Build a plan grouped by rule code, not a one-off patch per line.
4. For each violation, decide real fix vs. suppress-with-`noqa`:
   - **Default to a real fix.** `select = ["ALL"]` in `pyproject.toml` is deliberate —
     the project wants the strict ruleset enforced, not relaxed.
   - **`# noqa` is legitimate only when:** the rule is a false positive for this exact
     case, or fixing it would fight an established pattern already accepted in
     `pyproject.toml`'s `ignore` list philosophy (e.g. Typer's bool positional args,
     inline exception messages). If in doubt, treat it as a case-by-case judgment,
     not a default — document the reason in the `noqa` comment
     (`# noqa: RULE — reason`).
   - **Never blanket-suppress** a whole file or add a rule to the project-wide
     `ignore` list to make a violation disappear. That is a scope decision for the
     user, not an automatic fix.
5. Delegate the grouped fix plan to the `python-dev` agent with the plan, affected
   files, and the ruff rule codes involved.
6. Definition of done: `make lint` passes clean, changes committed.

## Trigger 2 — low test coverage

1. Run `make test` (`uv run pytest`, which already runs with
   `--cov=margot --cov-report=term-missing --cov-fail-under=90`) and capture the
   per-file coverage table from the terminal report.
2. Select the 1-2 files with the lowest coverage — not every under-covered file at
   once. Read the file and its existing test file (if any) to see what's actually
   untested (the `Missing` line-number ranges in the report point at this directly).
3. Build a short plan: what behavior is untested, what test(s) to add, which file(s)
   they land in (mirror the existing `tests/unit/` / `tests/integration/` /
   `tests/e2e/` split already used in this repo).
4. Delegate to `python-dev` with the plan and the specific uncovered line ranges.
   Tests must assert real behavior — no stub tests that just exercise a line without
   checking an outcome (same TDD rule as `code-conventions.md`).
5. Definition of done: `make test` passes, coverage for the targeted file(s)
   measurably improves, changes committed.

## Trigger 3 — global (non-selective) imports

1. Search for violations:
   ```bash
   grep -rn -E "^import " src/ tests/
   ```
   This catches `import x` module-level imports; selective imports (`from x import y`)
   are the required convention (see `code-conventions.md`) and won't match.
2. For each match, check whether a selective form is actually possible — a handful of
   modules are conventionally imported as a namespace (e.g. `import margot.console as
   console`, which the project's own conventions explicitly require — don't "fix" that
   one). Distinguish real violations from accepted namespace-import patterns before
   planning a change.
3. Build a plan: for each real violation, the selective import form it should become,
   and every usage site in that file that needs updating to match (e.g. `pytest.raises`
   → `from pytest import raises` then all call sites).
4. Delegate to `python-dev` with the plan and file list.
5. Definition of done: `grep -rn -E "^import " src/ tests/` shows only accepted
   namespace-import patterns, `make lint` and `make test` still pass, changes
   committed.

## Common rules across all three triggers

- Always run the relevant `make` target yourself first — don't plan from memory or
  assumption of what's currently failing.
- Group fixes into a coherent plan before delegating; don't delegate raw tool output.
- Delegate implementation to `python-dev` — this skill does not write code directly.
- A trigger is not done until its verification command passes clean and the fix is
  committed (conventional commit format), matching the repo's definition-of-done
  pattern used elsewhere (sprints, TODO fixes).
