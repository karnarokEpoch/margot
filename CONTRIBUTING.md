# Contributing to margot

By participating in this project, you agree to abide by the
[Code of Conduct](CODE_OF_CONDUCT.md).

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

See [the documentation](https://karnarokepoch.github.io/margot/) for the full spec and [AGENTS.md](AGENTS.md) for
architecture constraints.

## Commit conventions

Commits follow [Angular Commits Standard](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md):

```text
feat: add fetch command
fix: handle empty manifest response
refactor(infra): simplify OrasClient wrapper
docs: update command reference
test: add E2E for fetch command
chore: bump ruff
```

Changelog is generated from these prefixes via [git-cliff](https://git-cliff.org/).

## CI

Runs on every push to `main` and every PR:

- **Lint** — `make lint`
- **Test** — `make test` on Python 3.12 + 3.13 + 3.14

CI must pass before merge.

## Release process

Releases follow a branch-based flow — no manual tagging.

### Steps

1. Create a branch named `release/<version>` (e.g. `release/0.2.0`):

    ```bash
    git checkout -b release/0.2.0
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
    - Runs the **"Publish container image"** job: first runs the shared
        `.github/actions/build-verify-image` action (same action used by Container Check) —
        builds `linux/amd64` + `linux/arm64` into a throwaway local registry, asserts both
        platforms are in the image index, and runs `margot --version` on each. Only after
        that passes does it log in to GHCR and promote the tested image (same digest, copied
        with `skopeo copy --all --preserve-digests`) to
        `ghcr.io/karnarokepoch/margot:<version>` and `:latest`. GHCR login and the push are
        the only steps not exercised before a real release.

### Container check

The **Container Check** workflow (`.github/workflows/container-check.yml`) is test-only
and runs on **every pull request** (no path filter, including `release/*` PRs). It:

1. Builds the wheel and runs the shared `.github/actions/build-verify-image` action:
    builds `linux/amd64` + `linux/arm64` into a throwaway local registry, asserts both
    platforms are present in the image index, and runs `margot --version` on each.
2. Rehearses the promote step against a second throwaway local registry (port 5001,
    stand-in for GHCR), using the same `promote-image.sh` script as the release job.

Nothing is published. The only steps not exercised here are the GHCR login and the
push to `ghcr.io`.

### Versioning

- Version is derived from git tags via `hatch-vcs` — no version string in source.
- Tags pushed by the release workflow follow the branch name exactly
    (e.g. branch `release/0.2.0` → tag `0.2.0`).

### No manual tags

Do not push tags manually. The release workflow owns tagging to ensure the tag
always points to the merged commit on `main`.
