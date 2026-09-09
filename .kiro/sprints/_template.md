# Sprint Template

Copy this file to `sprint-N.md` and fill in the sections. The sprint file is the authoritative design for a release.

**Status:** in-flight (or completed)
**Type:** feature (or chore, docs, fix, refactor)
**Owner:** [dev agent(s)]
**Release:** planned for `release/X.Y.Z` (or link to merged release)

---

## 1. Goal

One-line summary of the vertical slice this sprint ships. Example: "Remote describe and verify with optional OCI URI."

---

## 2. Context

Background: why this sprint, what problem does it solve, what gaps does it fill? How does it fit into the product roadmap?

Authoritative references and dependencies (prior sprints, GitHub issues, ROADMAP entries, linked docs).

---

## 3. Authoritative Design

The contract this sprint implements against. Include:

- **Scope** — what *is* included; what is *not*.
- **User-visible behavior** — commands, flags, options, output changes.
- **Contracts** — function signatures, data flows, mutual exclusions, error cases.
- **Dependencies** — new libraries, updated existing APIs, layer changes.
- **Non-goals** — explicitly state what is deferred or out of scope.

Example structure:
```
### Item 1 — New `--foo` flag

- Applies to: `build`, `push`
- Effect: ...
- Default: ...
- Error case: ...

### Item 2 — Exit code table

- `0` — success
- `1` — validation error
- etc.
```

---

## 4. Checkable Steps

Tasks that must be completed for this sprint to be done. Structure by concern (e.g., code, tests, docs).

Example:
- [ ] Implement `services/foo.py::new_function` + unit tests
- [ ] Update `commands/bar.py` to call the new function
- [ ] E2E test: `margot foo --new-flag value`
- [ ] Update docs command-reference page
- [ ] Run `make docs-check` — must pass
- [ ] All changes committed

---

## 5. Definition of Done

What "done" looks like for this sprint. Checklist format:

- [ ] All checkable steps completed.
- [ ] `make check` passes (lint + unit + integration tests).
- [ ] E2E tests pass.
- [ ] Docs updated and `make docs-check` passes.
- [ ] No TODOs left (or explicitly deferred to next sprint in a comment).
- [ ] All changes committed to a feature branch.
- [ ] PR open to `main` with a clear description.
- [ ] Code review approved.

---

## 6. Close-out Note

Placeholder for close-out instructions. Filled in after merge:

```
Merged as commit [hash]. Backfilled ROADMAP Completed table with [release link].
Sprint file deleted via chore(sprint) commit [hash].
```

---

## References

- [Workflow & Authority Model](./../steering/workflow.md) — process loop, authority chain, N:M cardinality.
- [ROADMAP.md](./../../ROADMAP.md) — forward register and current sequencing.
- [CONTRIBUTING.md](./../../CONTRIBUTING.md) — commit conventions and release workflow.
