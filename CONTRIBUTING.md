# Contributing to margot

## Prerequisites

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) (package manager)

## Setup

```bash
git clone https://github.com/karnarokEpoch/margot.git
cd margot
uv sync
```

## Development

### Commands

```bash
make test    # run pytest with coverage
make lint    # ruff check (no auto-fix)
make fmt     # ruff format
make check   # lint + test
```

### Code style

- Formatter & linter: **ruff** (config in `pyproject.toml`)
- All imports absolute — no relative imports
- Target: Python 3.12, line length 130

### Architecture

Layered: `commands/` → `services/` → `domain/` + `infra/`.
Inner layers never import outer ones. `domain/` is pure Python (no I/O).

See [FEATURES.md](FEATURES.md) for the full spec and [AGENTS.md](AGENTS.md) for
architecture constraints.

## Commit conventions

Commits follow [Angular Commits Standard](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md):

```text
feat: add fetch command
fix: handle empty manifest response
refactor(infra): simplify OrasClient wrapper
docs: update FEATURES.md fetch section
test: add E2E for fetch command
chore: bump ruff
```

Changelog is generated from these prefixes via [git-cliff](https://git-cliff.org/).

## CI

Runs on every push to `main` and every PR:

- **Lint** — `make lint`
- **Test** — `make test` on Python 3.12 + 3.13

CI must pass before merge.

## Release process

Releases follow a branch-based flow — no manual tagging.

### Steps

1. Create a branch named `release/<version>` (e.g. `release/v0.2.0`):

   ```bash
   git checkout -b release/v0.2.0
   ```

2. Push and open a PR to `main`. The **Release Check** workflow previews
   the changelog in CI output.

3. Review & merge the PR.

4. On merge, the **Release** workflow automatically:
   - Extracts the version from the branch name
   - Tags the merge commit
   - Builds the package (`uv build`)
   - Generates release notes via `git-cliff`
   - Creates a GitHub Release with the built artifacts

### Versioning

- Version is derived from git tags via `hatch-vcs` — no version string in source.
- Tags pushed by the release workflow follow the branch name exactly
  (e.g. branch `release/v0.2.0` → tag `v0.2.0`).

### No manual tags

Do not push tags manually. The release workflow owns tagging to ensure the tag
always points to the merged commit on `main`.
