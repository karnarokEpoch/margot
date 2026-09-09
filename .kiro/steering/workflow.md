---
inclusion: manual
---

# Workflow & Authority Model

The canonical process loop for building features and shipping releases.

## Authority chain

Truth flows through three live sources, one archival:

| Artifact | Role | Authority | Horizon |
|---|---|---|---|
| `ROADMAP.md` | Forward register: upcoming features, fixes, ideas, backlog. A queue of *intent*, not a spec. | What to build next. | Future |
| `.kiro/sprints/sprint-N.md` | **Authoritative design** upfront, for the release being built. What the dev agent implements against and what "done" is judged against. Deleted on close-out. | How to build it, right now. | In-flight |
| `docs/` (MkDocs) | **Standing source of truth for shipped behavior.** | What users can do, today. | Shipped / present |
| Git history | Archives of each sprint's design via close-out commits. | Historical record. | Archive |

Sprint files are deleted on close-out; **git history is the archive.** A conventional close-out commit makes each sprint's design easy to find: `chore(sprint): close out sprint-N — <capability>`.

## The process loop

### Idea → ROADMAP

An idea, fix, or improvement is opened as a GitHub issue or discussed in planning. The `planner` agent (or project owner) decides:

- **Feature:** Add to ROADMAP backlog, tagged `enhancement`. Promote to sprint as part of sprint planning.
- **Fix:** Add to ROADMAP backlog, tagged `bug` or `fix`. Can be pulled into any release without a sprint; no sprint file needed.
- **Docs:** Lands with the feature that introduced the behavior, or ships independently without a sprint.

The ROADMAP is the queue of intent — all work lives here first.

### ROADMAP → Sprint file

At sprint planning, one or more ROADMAP items are selected and moved from "Backlog" to "Planned Sprints" section. The `planner` creates a `.kiro/sprints/sprint-N.md` file with:

- **Goal** — what this sprint ships (one vertical capability).
- **Authoritative design** — contracts, data flows, scope, mutual exclusions.
- **Checkable steps** — per-feature tasks, file changes, test requirements.
- **Definition of done** — what passes review.
- **Close-out note** — placeholder for sprint close-out instructions.

See `.kiro/sprints/_template.md` for the standard shape.

### Sprint → `release/<version>` branch

Dev work follows the sprint file as the authoritative design. On completion:

1. Create a `release/<version>` branch (e.g. `release/0.2.0`).
2. Update ROADMAP — move the completed sprint from "Planned Sprints" to "Completed Sprints" table with **a release link** (GitHub release URL, once the release is published).
3. Run close-out tasks (see Close-out checklist below).
4. Open a PR to `main`.
5. Review & merge.

On merge, the GitHub release workflow automatically tags, builds, and publishes.

### Release → Close-out

After merge, in the **release PR** (before merge), or immediately after:

- [ ] **Docs updated.** `make docs-check` passes (strict build). User-facing behavior is documented in `docs/`.
- [ ] **ROADMAP updated.** Completed sprint moved to the Completed Sprints table **with the GitHub release link** (e.g. `[0.2.0](https://github.com/karnarokEpoch/margot/releases/tag/0.2.0)`). Backlog reviewed and trimmed if needed.
- [ ] **Sprint file deleted.** In a single commit with the message: `chore(sprint): close out sprint-N — <capability>` (e.g. `chore(sprint): close out sprint-9 — remote describe and verify`).
- [ ] **No dangling references.** `grep -r "FEATURES\.md"` or `grep -r "sprint-N"` (for N = current sprint) returns zero (exception: the plan file itself, if it still exists).

After close-out, the sprint file is gone; git history preserves its design via the close-out commit message and the `git log` for that release.

## Cardinality: N:M sprints ↔ releases

- **One sprint can land in one release.** Typical: a single feature sprint ships in a minor version.
- **Multiple sprints can land in one release.** E.g. Sprint 9 (remote describe/verify) + Sprint 10 (stable exit codes) + docs + fixes → release 0.10.0.
- **One sprint can span multiple releases.** Rare, but if a feature is deferred mid-sprint, the sprint file stays open until the feature ships.
- **Fixes land without a sprint.** Bug fixes, chores, and docs amendments go straight to a `release/<patch>` branch or fold into the next release. `ROADMAP.md` tracks them in git-cliff commit messages (`fix:`, `chore:`, `docs:` prefixes), not in a sprint file.

## When a fix needs no sprint

Fixes, chores, and docs fixes **never** require a sprint file. They:

1. Are tracked in ROADMAP backlog with a `bug` or `fix` label.
2. Can be pulled into any release without scheduling.
3. Land via commits with `fix:`, `chore:`, or `docs:` prefixes — git-cliff auto-includes them in the changelog.
4. Close-out still applies: update ROADMAP Completed table and commit with `chore: ...` message.

## N:M example walkthrough

Sprint 9 ships remote describe/verify. Sprint 10 ships exit codes. Three fixes land in the interim.

**Release 0.9.0** (minor):
- Sprint 9 feature.
- Three fixes from backlog.
- Docs for Sprint 9.

**Release 0.10.0** (minor):
- Sprint 10 feature.
- Two more fixes.
- Docs for Sprint 10.

**Release 0.10.1** (patch):
- One critical fix.
- No sprint involved.

Both releases use the same `release/<version>` branch and auto-release workflow; the cardinality is transparent.

## Close-out checklist (before merge to main)

Use this for every release. It is the gate to green.

### Documentation

- [ ] All user-facing behavior is documented in `docs/` (command reference, config page, examples, etc.).
- [ ] `make docs-check` passes (strict MkDocs build; warnings are errors).
- [ ] Internal links are correct (no broken nav entries).

### ROADMAP update

- [ ] Completed sprint moved to Completed Sprints table.
- [ ] Release link is present: `[0.2.0](https://github.com/karnarokEpoch/margot/releases/tag/0.2.0)`.
- [ ] Backlog reviewed; stale or deferred items are trimmed or moved.

### Sprint close-out

- [ ] Sprint file deleted in a commit: `chore(sprint): close out sprint-N — <capability>`.
- [ ] Example: `chore(sprint): close out sprint-9 — remote describe and verify`.

### Refs & integrity

- [ ] No dangling FEATURES.md references (exception: sprint-workflow-rework.md, the plan file itself).
- [ ] No dangling sprint-N references (exception: git history, which is fine).
- [ ] All files committed before merge.

---

## See also

- `.kiro/sprints/_template.md` — uniform sprint-file shape.
- `ROADMAP.md` — current queue of work.
- `CONTRIBUTING.md` — release branch mechanics and CI flow.
