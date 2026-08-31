# Sprint 9 — `--json` output and stable error codes

**Goal:** Make margot's output and failure modes machine-consumable, without changing
any human-facing rich rendering by default. An agent (or script) driving margot today
has exactly one structured surface (`fetch`'s raw manifest JSON) and one failure signal
(`Exit(1)` + an English sentence on stderr) — everywhere else it must screen-scrape rich
panels/trees or string-match error text. This sprint closes both gaps.

**Prerequisite:** none — orthogonal to Sprint 8 (`describe` traversal/orphan work).
Can run in parallel or before/after; touches `console.py` and every `commands/*.py`
file, not `domain/describe.py`'s data model itself (Sprint 8's new dataclasses should
serialize for free once this lands, if Sprint 8 ships first — see Item 1 ordering note).

---

## Context: current state (verified against source)

- `console.print_json` exists (`src/margot/console.py`) but only `fetch` uses it — every
  other command (`build`, `push`, `pull`, `verify`, `describe`) is rich-text/panel-only,
  with no structured alternative.
- `console.fatal()` (22 call sites across `auth.py`, `build.py`, `push.py`, `pull.py`,
  `fetch.py`, `verify.py`, `describe.py`) always: prints a free-text `str` to stderr,
  raises `Exit(1)`. Every failure — bad flag, expired credentials, network error,
  SemVer violation, unloadable descriptor — collapses to the same exit code. Nothing
  distinguishes them but message wording.
- `domain/validation.py` already has clean, serializable dataclasses:
  `ValidationFinding` (`field_path`, `message`, `severity`), `VerifyResult`
  (`schema_a_results`, `schema_b_results`, `schema_a_version`, `passed`). No `rich`
  import — trivial to serialize as-is.
- `domain/describe.py`'s display dataclasses (`Identity`, `Catalog`, `DeploymentProfile`,
  `Configuration`, etc.) are equally clean — pure data, no `rich` import (per
  rich-rendering.md's layering rule: `domain/` never imports `rich`).
- stdout/stderr separation is already correct and should be preserved exactly:
  `success`/structured-data → stdout (pipeable), `warning`/`info`/`debug`/`fatal` →
  stderr. This sprint extends the pattern, doesn't change it.
- Global flags (`-v`/`-d`/`-V`) are wired once via `app.callback()` in
  `commands/global_options.py`, backed by module-level flags in `console.py`
  (`set_verbose`/`set_debug`). `--json` should follow the identical shape.

---

## Scope

### Item 1 — `--json` flag on `describe` and `verify`

These two are the highest-value read commands for an agent: "what's in this descriptor"
and "is it valid." Both already have fully-built display/result dataclasses with zero
`rich` coupling — this is a serialization problem, not a data-modeling one.

**`margot verify --json`:**
```json
{
  "passed": false,
  "schema_a_version": "45f4359",
  "schema_a_results": [
    {"field_path": "deploymentProfiles[0].components[1].name", "message": "...", "severity": "ERROR"}
  ],
  "schema_b_results": []
}
```
Direct `dataclasses.asdict`-style dump of `VerifyResult`, `Severity` as its string value.
No new fields — this is the same data `verify`'s pass/fail lines are already built from.

**`margot describe --json`:**
Dump whichever sections were requested via `--section` (same selection logic, same
default-set behavior) as a single JSON object keyed by section name (`metadata`,
`profiles`, `config-first` / `component-first` if Sprint 8 has landed, `extensions`).
Structure mirrors the display dataclasses directly — no rich-specific concepts (no tree
depth, no panel titles) leak into the JSON; e.g. the "immutable" flag is a plain
`"immutable": true` field, not a rendered `[Setting] immutable` string.

**Design decision (needs confirmation before implementation):** is `--json` a boolean
flag that *replaces* rich output (`describe --json` prints only JSON, nothing else), or
does it live alongside `--section` as an output-mode toggle usable with any section
selection? Leaning toward: boolean flag, mutually exclusive with nothing, always replaces
rich rendering entirely when passed — one command, one output contract per invocation,
no mixed stdout.

**Files:**
- `src/margot/commands/verify.py`, `src/margot/commands/describe.py` — add `--json`,
  branch to `console.print_json` instead of panel/text rendering.
- `src/margot/console.py` — no change expected; `print_json` already exists.
- Unit tests: JSON output asserted against the same fixtures already used for the rich
  rendering tests (sensor-dashboard descriptor, existing verify fixtures) — same input,
  assert the JSON shape instead of screen text.
- `FEATURES.md` — document the flag and shape per command.

### Item 2 — Stable error codes

Replace the single `Exit(1)` catch-all with a small, closed set of exit codes, so a
caller can branch without string-matching. Proposed taxonomy (subject to review — this
is the one open design decision that needs a decision before coding):

| Code | Meaning | Example current call sites |
|---|---|---|
| `0` | Success | — |
| `1` | Generic/unexpected failure (fallback — every current bare `except Exception` case) | `build.py:88`, `push.py:91`, `pull.py:56`, `fetch.py:20/22` |
| `2` | Usage error — bad flag/argument combination, caught before any I/O | `verify.py:39` (mutually exclusive flags), `build.py:20`/`push.py:20` (invalid `--type`), `pull.py:33` (invalid `--force-type`), `auth.py:54/57/61` (missing credentials input) |
| `3` | Validation failure — the input was well-formed but semantically invalid (SemVer, schema, descriptor load gate) | `verify.py:86/138` (schema failures), `describe.py:478` (unloadable descriptor), `build.py:86` (SemVer/metadata error) |
| `4` | Remote/auth failure — registry unreachable, credentials expired/rejected | `auth.py:74/86` (login/logout failure), `push.py:89` (push failure — may need finer split between local validation and remote failure inside `services/push.py`) |

**Open question:** several `fatal()` sites currently wrap a caught `Exception` with a
generic message (`f"Build failed: {e}"`) without distinguishing *why* it failed — the
exception type is already known at the catch site, just discarded. Assigning the right
code means inspecting what exception types `services/*.py` actually raises today
(`ValueError`, `TypeError`, oras-py exceptions, etc.) and mapping each to a category
*before* implementation — this needs a short audit pass per command, not a guess.

**Implementation shape:**
- `console.fatal(message: str, code: int = 1)` — add an optional `code` param, default
  preserves today's behavior for any call site not yet updated (no silent behavior
  change for callers not touched this sprint).
- Update call sites incrementally, command by command, each as its own commit — 22 call
  sites across 7 files is enough surface area to regress silently if done as one sweep.
- `FEATURES.md` gets a new "Exit codes" reference table — this is the authoritative
  contract callers (including agents) rely on; once published, codes should be treated
  as stable API, same weight as the OCI media type table.

**Files:** `src/margot/console.py`, all 7 command files with `fatal()` calls,
`FEATURES.md`.

### Item 3 — `--json` error envelope (depends on Item 2)

Once exit codes exist, pair them with a structured error on stderr when `--json` is
active, so a caller doesn't need *both* the exit code *and* to parse English:

```json
{"error": true, "code": 3, "message": "Schema A: FAIL — 2 errors, 0 warnings"}
```

Only emitted when `--json` was passed for that invocation — a script not asking for JSON
still gets today's plain-English `Error: ...` line. `console.fatal()` needs to know
whether the current invocation is in JSON mode (module-level flag, same pattern as
`_verbose`/`_debug`) to choose the envelope vs. the prose line.

**Files:** `src/margot/console.py` (`set_json_mode` / `is_json_mode`, branch in
`fatal()`), same command files as Item 2.

### Item 4 — `--no-color` / `NO_COLOR` support

Rich auto-detects non-TTY and usually suppresses color when piped, but an explicit,
guaranteed-off switch removes ambiguity for a caller capturing output into logs it
stores or re-displays. Support both an explicit `--no-color` flag and the `NO_COLOR`
env var convention (https://no-color.org) — check `NO_COLOR` presence in
`global_options.py` alongside the existing `-v`/`-d` wiring, force rich's
`Console(no_color=True)` at the `_get_stdout`/`_get_stderr` factories in `console.py`.

**Files:** `src/margot/console.py`, `src/margot/commands/global_options.py`.

---

## Out of scope (explicitly deferred)

- `build`/`push`/`pull` gaining `--json` — these are action commands whose primary value
  is the side effect (files written, artifact pushed), not information retrieval. Their
  `success()` line could grow a structured counterpart later, but `describe`/`verify`
  are the clear first targets; revisit after those ship and prove the pattern.
- Retrying/backoff logic, or any agent-side tooling — this sprint only makes margot's
  own output/exit contract legible; it does not add agent orchestration features.
- Changing default (non-`--json`) output in any way — every existing rich panel, tree,
  and `console.success` line stays exactly as-is for interactive/human use.

## Decisions needed before implementation

1. Does `--json` fully replace rich output for that invocation, or can it combine with
   partial `--section` selection on `describe`? (Leaning: full replace, see Item 1.)
2. Final exit code taxonomy (Item 2 table above is a proposal, not locked) — needs a
   pass through `services/*.py` to confirm what exceptions are actually raised where,
   rather than assigning codes from the command layer's current generic catches alone.
3. Whether `--json` and `--no-color` are per-command flags or promoted to
   `global_options.py` like `-v`/`-d`/`-V` — global is more consistent with existing
   convention but `--json` only makes sense on commands that produce structured output today.
