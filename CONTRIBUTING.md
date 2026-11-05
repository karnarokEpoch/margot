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

The **Release** workflow owns tagging. There are two routes:

- a `release/<version>` branch and PR, for a release that includes new commits (the steps below);
- a manual run of the **Release** workflow on `main`, for a commit that is already tagged, such as promoting the
    pre-release `0.12.1-rc0` to `0.12.1` (see [Promoting to a final release](#promoting-to-a-final-release)).

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
    - Creates a GitHub Release with the built artifacts (marked as pre-release for
        versions containing `-`, e.g. `0.12.1-rc0`)
    - Runs the **"Publish container image"** job: first runs the shared
        `.github/actions/build-verify-image` action (same action used by Container Check) —
        builds `linux/amd64` + `linux/arm64` into a throwaway local registry, asserts both
        platforms are in the image index, and runs `margot --version` on each. Only after
        that passes does it log in to GHCR and promote the tested image (same digest, copied
        with `skopeo copy --all --preserve-digests`) to
        `ghcr.io/karnarokepoch/margot:<version>` and, for stable releases only, `:latest`.
        Pre-release versions receive `:<version>` only — `:latest` is not moved. GHCR login
        and the push are the only steps not exercised before a real release.

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
- Tags pushed by the release workflow follow the version exactly: the branch name for PR releases
    (branch `release/0.2.0` → tag `0.2.0`), or the `version` input for manual runs.

### No manual tags

Do not push tags manually. The release workflow creates the tag: on the merge commit for PR releases, and on
the current HEAD of `main` for manual runs, so the tag always matches the commit being released.

### Release candidates and pre-releases

A version containing `-` (e.g. `0.12.1-rc0`, `1.0.0-beta.1`) is treated as a pre-release
throughout the pipeline:

| Concern        | Stable release                     | Pre-release                                                       |
| -------------- | ---------------------------------- | ----------------------------------------------------------------- |
| GitHub Release | Marked "Latest"                    | Marked `--prerelease` (not shown as "Latest")                     |
| GHCR tags      | `:<version>` + `:latest`           | `:<version>` only — `:latest` not moved                           |
| PyPI           | Published automatically on release | Skipped automatically; manual `workflow_dispatch` still publishes |

#### Cutting a release candidate

Use the same branch-based flow as a stable release: `release/0.12.1-rc0` → PR to `main` → merge.
The pipeline detects the `-` and applies the pre-release rules above automatically.

#### Promoting to a final release

Use this route when `main` already holds everything the final release needs. The final release is cut from the
tagged commit: no new branch, commit or PR is required.

1. Check that `main` is at the commit to release and that the commit already carries the pre-release tag
    (for example `0.12.1-rc0`).
2. In GitHub, open **Actions → Release → Run workflow**. Keep the branch on `main` and enter the version without a
    leading `v`, for example `0.12.1`.

The release jobs run only when the run is on `main`. Before anything is tagged, the guard in
`.github/scripts/check-tagged-release.sh` requires that:

- the version is SemVer (for example `0.12.1`);
- HEAD already carries at least one tag. The tag's kind is not checked, so a pre-release tag is enough. An
    untagged HEAD is rejected: release that commit through the `release/<version>` PR route instead;
- the requested tag does not exist yet, locally or on `origin`.

When the guard passes, the workflow:

- tags HEAD with the requested version and pushes the tag;
- builds the wheel with that version and fails if the wheel does not carry it;
- generates release notes for the commits since the previous release (for `0.12.1`, `0.12.0..HEAD`; for a
    pre-release, since the previous tag of any kind);
- creates the GitHub release (a stable version is marked Latest) and publishes the container image as
    `:<version>` and, for stable versions, `:latest`;
- for a stable version, publishes to PyPI once the Release workflow succeeds.

Use the `release/<version>` PR route instead when the final release needs new commits, such as a changelog or
documentation touch-up. Create `release/0.12.1` from `main`, open the PR and merge it. The workflow then tags the
merge commit.

Do not push tags manually.

#### If only the container job fails

Use **"Re-run failed jobs"** (not "Re-run all jobs"): the tag and GitHub release already
exist at that point, and the `build-artifacts` artifact is retained for one day.
Re-running all jobs would attempt to create a duplicate tag and release. A manual run's guard
also refuses to start again once its tag exists, so a re-run cannot repeat the tagging step.
