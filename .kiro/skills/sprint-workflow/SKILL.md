---
name: sprint-workflow
description: >
  Sprint planning, release workflows, and the canonical authority model: idea → ROADMAP → sprint file → release → close-out.
  Covers N:M sprint/release cardinality, when fixes need no sprint, and the release close-out checklist.
  Use only when planning a sprint, opening a release, or closing one out; not on every request.
---

# Sprint Workflow Skill

## When to use

Only when:
- Planning a new sprint (selecting items from ROADMAP, creating a sprint file).
- Opening or managing a `release/<version>` branch.
- Closing out / deleting a sprint file at release time.
- Answering questions about the sprint/release authority model.

Do **not** run this workflow proactively during doc writing, code implementation, or unrelated planning requests. This skill is for process orchestration at sprint boundaries, not every planning step.

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

**To create a new sprint:** Copy `sprint-template.md` from this skill into `.kiro/sprints/sprint-N.md` (where N is the next sprint number) and fill in each section per the template's instructions.

### Sprint → feature branches → `release/<version>` branch

Git orchestration is split across three roles, gated by two owner checkpoints. Parallel-worktree mechanics live in the **`agent-workspace`** skill; this is the summary.

**The project owner:**

1. Creates the `release/<version>` branch (e.g. `release/0.2.0`).
2. **Gate 1:** validates the planner's item → branch → worktree split before any branch is created.
3. **Gate 2:** reviews the completed, committed work before it is pushed.
4. Opens the PR onto the release branch, reviews, and merges. Merging the release branch to `main` triggers the GitHub release workflow (auto tag, build, publish).

**The planner** (see `agent-workspace` for the full flow and commands):

1. Proposes the item → branch → `.wk-<name>/` worktree split for owner validation (Gate 1).
2. After Gate 1: creates each branch + worktree (`git worktree add -b`) and launches a dev agent into each.
3. After Gate 2: pushes each branch and removes the worktrees. **Never** opens or merges PRs.

**The dev agent (inside its assigned `.wk-<name>/` worktree):**

1. Implements its item following the sprint file as authoritative design.
2. Commits its work with conventional-commit messages — **one or more commits per task**, never one bulk commit for the whole sprint. Each task (a checkable step / sprint item) lands as at least one self-contained commit, so history is reviewable task-by-task and the owner can drop or reorder tasks cleanly.
3. Runs close-out tasks it is responsible for — updating ROADMAP, docs, deleting the sprint file (see Close-out checklist below).

The dev agent **must not**: create branches or worktrees, `git push`, `git worktree remove`, or open/merge PRs. **Commit — never push — is the dev agent's boundary.** If a step requires more, it hands back to the planner (who acts only after the owner's gates).

### Release → Close-out

Close-out work is done by the dev agent **on its worktree branch, before Gate 2 review**. The agent commits these changes; after the owner's review the planner pushes, and the owner opens the PR and merges:

- [ ] **Docs updated.** `make docs-check` passes (strict build). User-facing behavior is documented in `docs/`.
- [ ] **ROADMAP updated.** Completed sprint moved to the Completed Sprints table **with the GitHub release link** (e.g. `[0.2.0](https://github.com/karnarokEpoch/margot/releases/tag/0.2.0)`). Backlog reviewed and trimmed if needed.
- [ ] **Sprint file deleted.** In a single commit with the message: `chore(sprint): close out sprint-N — <capability>` (e.g. `chore(sprint): close out sprint-9 — remote describe and verify`).
- [ ] **No dangling references.** `grep -r "FEATURES\.md"` or `grep -r "sprint-N"` (for N = current sprint) returns zero (exception: the plan file itself, if it still exists).

The GitHub release link may not exist until after the owner merges and the release workflow publishes — in that case the agent adds the row with a `—` placeholder or the anticipated URL, and the owner finalizes it. After close-out the sprint file is gone; git history preserves its design via the close-out commit message.

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

## Close-out checklist (dev agent commits; planner pushes after review; owner merges)

Use this for every release. The dev agent completes and commits these on its worktree branch; after Gate 2 review the planner pushes, and the owner opens the PR and merges. It is the gate to green.

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

- `sprint-template.md` — uniform sprint-file shape (copy into `.kiro/sprints/sprint-N.md`).
- `agent-workspace` skill — parallel `.wk-<name>/` worktree orchestration: split, gates, `git worktree` commands, and in-worktree agent rules.
- `ROADMAP.md` — current queue of work.
- `CONTRIBUTING.md` — release branch mechanics and CI flow.
