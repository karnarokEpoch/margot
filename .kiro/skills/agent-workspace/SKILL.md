---
name: agent-workspace
description: >
  Orchestrate parallel agent work across isolated git worktrees. Split a validated sprint
  into item → branch → `.wk-<name>/` worktree, then create worktrees, launch a dev agent
  into each, and (after review) push and tear down. Use only when setting up or coordinating
  multi-agent parallel work in worktrees, or when an agent must understand it is operating
  inside a `.wk-` worktree — not on every task.
---

# Agent Workspace Skill

## When to use

Only when:
- Splitting a validated sprint into parallel items, each on its own branch + worktree.
- Creating, launching agents into, pushing, or tearing down `.wk-<name>/` worktrees.
- An agent needs to understand it is operating **inside** a dedicated `.wk-` worktree and must stay there.

Do **not** run this workflow for a single-branch task, during ordinary doc/code work, or unrelated planning. This skill is for orchestrating *concurrent, isolated* agent work — not every implementation step.

---

# Parallel Worktree Orchestration

Run multiple items from a sprint in parallel, each in its own git worktree on its own branch, so concurrent work never collides. The **planner** sets up and dispatches; **dev agents** work in-folder and commit; the **owner** gates the flow twice and owns PR/merge.

## Concept

A `.wk-<name>/` directory is a **git worktree** — a full, independent checkout of one branch, living inside the repo root but ignored via `.wk-*/` in `.gitignore`. Each worktree:

- Is on **its own branch** and can be at a **different commit** than the parent checkout. Never assume parity — a worktree branched earlier may hold stale files (e.g. a pre-retirement `FEATURES.md`). Act on the worktree's own tree, not the parent's state.
- Has its **own `.venv`** — `uv run` / `make` inside a worktree use *that* worktree's environment. Run `uv sync` once after creating it.
- Isolates one item/task and (typically) one agent, so parallel work on different sprint items stays independent.

One item → one branch → one `.wk-<name>/` → one agent.

## Naming

- **Worktree folder:** `.wk-<short-item-name>/` — e.g. `.wk-webdoc`, `.wk-exit-codes`, `.wk-alpha`.
- **Branch:** `<type>/<item>` per commit conventions — e.g. `docs/update-website-documentation`, `feat/exit-codes`, `fix/pull-semver-gate`.
- Keep the folder suffix short and the branch descriptive; they need not match verbatim.

## The orchestration flow

Two human gates. The planner never crosses either on its own.

```
propose split
   │
   ▼
[GATE 1 — owner validates the split]      ← planner stops, waits
   │
   ▼
planner: git worktree add -b <branch> .wk-<name>   (one per item)
planner: launch a dev agent into each worktree
   │
   ▼
dev agent: implement + commit per task, inside its own .wk-<name>/
   │
   ▼
[GATE 2 — owner reviews the completed work]   ← planner stops, waits
   │
   ▼
planner: git push (per branch)
planner: git worktree remove .wk-<name>   (per item)
   │
   ▼
owner: open PR onto the release branch, review, merge
```

### 1. Propose the split (planner)

Decompose the validated sprint into items. Present a table mapping each to a branch and worktree, e.g.:

| Item | Type | Branch | Worktree |
|---|---|---|---|
| Feature A | feat | `feat/a` | `.wk-alpha` |
| Fix C | fix | `fix/c` | `.wk-delta` |

### 2. GATE 1 — owner validates the split

The planner **stops and waits** for the owner to approve the item→branch→worktree mapping. No worktrees are created and no agents are launched before approval.

### 3. Create worktrees + launch agents (planner, after Gate 1)

For each approved item, from the repo root:

```bash
# Create a new branch and its worktree in one step
git worktree add -b <branch> .wk-<name>

# Prepare the isolated environment (installs into the worktree's own .venv)
uv sync --directory .wk-<name>
```

Then launch a dev agent scoped to that worktree, instructing it to work **only** inside `.wk-<name>/` and to follow the `sprint-workflow` skill's per-task commit rule.

### 4. Implement (dev agent, inside its worktree)

The dev agent follows the sprint file as authoritative design, implements its assigned item, and commits **one or more commits per task** (see `sprint-workflow`). It stops at commit — see agent rules below.

### 5. GATE 2 — owner reviews

When agents finish and have committed, the planner **stops and hands back to the owner for review**. The planner never self-certifies. It proceeds only once the owner approves.

### 6. Push + tear down (planner, after Gate 2)

Only after review approval:

```bash
# Push the branch (from inside the worktree, or with -C)
git -C .wk-<name> push -u origin <branch>

# Remove the worktree once its branch is pushed
git worktree remove .wk-<name>
```

`.wk-*/` is gitignored, so removing a worktree leaves no trace in the parent's tracked state. If a worktree has uncommitted changes, `git worktree remove` refuses — resolve (commit or discard) before removing; never force-remove work that hasn't been reviewed.

### 7. PR + merge (owner)

The owner opens the PR onto the `release/<version>` branch, reviews, and merges. PR and merge are **owner-owned** and never done by the planner or a dev agent.

## Ownership boundary

| Operation | Owner | Planner | Dev agent |
|---|---|---|---|
| Approve the split | ✅ (Gate 1) | proposes | — |
| `git worktree add -b` | — | ✅ after Gate 1 | ❌ |
| `uv sync` in worktree | — | ✅ | (may re-run in its own worktree) |
| Launch dev agent into a worktree | — | ✅ | — |
| Implement + commit per task in-folder | — | — | ✅ |
| Review completed work | ✅ (Gate 2) | — | — |
| `git push` | — | ✅ after Gate 2 | ❌ |
| `git worktree remove` | — | ✅ after Gate 2 | ❌ |
| PR onto release branch, merge to `main` | ✅ | ❌ | ❌ |

## Agent rules inside a worktree

A dev agent launched into `.wk-<name>/`:

- Operates **only** within its assigned `.wk-<name>/`. Never reads, writes, or `cd`s into a sibling `.wk-*` worktree or back into the parent checkout.
- Uses **this worktree's** environment: `uv run <cmd>` / `make` resolve to `.wk-<name>/.venv`. Never a global tool.
- Commits per task with conventional-commit messages (`sprint-workflow` rule) — one or more commits per task, no bulk commit.
- **Must not** run `git worktree add`/`remove`, create branches, `git push`, or open/merge PRs. Commit is its boundary; it hands back to the planner.
- Treats the worktree's own tree as ground truth — does not assume parity with the parent repo (a behind branch may carry stale files).

## Gotchas

- **Stale files in a worktree.** A branch created before a repo-wide change carries the pre-change tree (e.g. `.wk-webdoc` still holds the retired `FEATURES.md`). Expected — the worktree is independent. Rebase/merge the base branch in if currency matters, but that is an owner decision.
- **`make` / tests run against the worktree.** Coverage, `docs-check`, and lint act on the worktree's files and its `.venv`, not the parent's.
- **Removal needs a clean tree.** `git worktree remove` refuses with uncommitted changes — never bypass review by force-removing.

---

## See also

- `sprint-workflow` skill — the process loop this feeds into; per-task commit rule; the release/close-out boundary.
- `.gitignore` — `.wk-*/` keeps all worktrees out of the parent's tracked state.
- `CONTRIBUTING.md` — branch/PR/CI mechanics and commit conventions.
