# margot

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
