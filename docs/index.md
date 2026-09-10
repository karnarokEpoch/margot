# margot

[![PyPI version](https://img.shields.io/pypi/v/margo-tooling)](https://pypi.org/project/margo-tooling/)
[![Python versions](https://img.shields.io/pypi/pyversions/margo-tooling)](https://pypi.org/project/margo-tooling/)
[![License](https://img.shields.io/pypi/l/margo-tooling)](https://github.com/karnarokEpoch/margot/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/karnarokEpoch/margot/ci.yml)](https://github.com/karnarokEpoch/margot/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://karnarokepoch.github.io/margot/)
[![Downloads](https://img.shields.io/pypi/dm/margo-tooling)](https://pypi.org/project/margo-tooling/)
[![Container](https://img.shields.io/badge/ghcr.io-margot-blue?logo=podman)](https://github.com/karnarokEpoch/margot/pkgs/container/margot)
[![Codecov](https://img.shields.io/codecov/c/github/karnarokEpoch/margot)](https://codecov.io/gh/karnarokEpoch/margot)
[![GitHub stars](https://img.shields.io/github/stars/karnarokEpoch/margot)](https://github.com/karnarokEpoch/margot)
[![GitHub forks](https://img.shields.io/github/forks/karnarokEpoch/margot)](https://github.com/karnarokEpoch/margot)
[![GitHub issues](https://img.shields.io/github/issues/karnarokEpoch/margot)](https://github.com/karnarokEpoch/margot/issues)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**margot** is a developer CLI for building and publishing Margo application packages as OCI artifacts. It handles
packaging, tagging, and pushing/pulling to any OCI-compliant registry.

## Install

```bash
pip install margo-tooling
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install margo-tooling
```

Or with [pipx](https://pipx.pypa.io/latest/index.html):

```bash
pipx install margo-tooling
```

For container, from-source, and shell completion setup, see the [Getting Started guide](guides/getting-started.md).

## Learn more

- [Getting Started](guides/getting-started.md) — install, minimal project, build, push, pull, shell completion.
- [Authentication](guides/authentication.md) — registry login, AWS ECR, credential expiry.
- [CI/CD integration](guides/ci-cd.md) — pipeline shape, verify/push gate primitives, credential handling.
- [GitHub repository](https://github.com/karnarokEpoch/margot)
- [PyPI package](https://pypi.org/project/margo-tooling/)
