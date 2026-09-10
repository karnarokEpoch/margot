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

**margot** is a developer CLI for building and publishing [Margo](https://margo.org) application
packages as OCI artifacts. It handles packaging, tagging, and pushing/pulling to any
OCI-compliant registry.

[Documentation](https://karnarokepoch.github.io/margot/) ·
[PyPI](https://pypi.org/project/margo-tooling/)

## Install

### From PyPI

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

### With a container

Every release publishes a container image to GHCR. Mount your project directory into
`/workspace`:

```bash
podman run --rm -v "$PWD":/workspace ghcr.io/karnarokepoch/margot:latest --help
```

Pin to a specific version instead of `latest` for reproducible builds, e.g.
`ghcr.io/karnarokepoch/margot:1.0.0`.

### From source

```bash
git clone https://github.com/karnarokEpoch/margot.git
cd margot
uv sync
```

## Usage

```
$ margot --help

 Usage: margot [OPTIONS] COMMAND [ARGS]...

 Margo application package developer CLI.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --version             -V        Print version and exit.                     │
│ --verbose             -v        Enable verbose output (step-level info).     │
│ --debug               -d        Enable debug output (infra-level detail,     │
│                                  implies --verbose).                         │
│ --install-completion            Install completion for the current shell.    │
│ --show-completion                Show completion for the current shell, to  │
│                                  copy it or customize the installation.      │
│ --help                -h        Show this message and exit.                 │
╰────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ─────────────────────────────────────────────────────────────────────╮
│ fetch     Fetch and display the manifest of an OCI artifact.                  │
│ build     Build Margo application package types locally.                     │
│ push      Push built Margo application artifacts to an OCI registry.         │
│ pull      Pull OCI artifact layers to a local directory.                     │
│ verify    Validate the Margo application description against the Margo spec │
│           schema.                                                            │
│ describe  Describe a Margo application description in rich, structured      │
│           output.                                                           │
│ auth      Manage OCI registry credentials.                                  │
╰────────────────────────────────────────────────────────────────────────────────╯
```

### A minimal project

A Margo project is described by a `margo.yaml` file at the project root:

```
nginx-helm/
├── margo.yaml
└── margo/
    └── app.yaml.jinja
```

```yaml
# margo.yaml
apiVersion: v1
id: com-example-nginx
name: nginx
version: "1.0.0"
appVersion: "1.27.0"
description: "NGINX web server deployed via Helm chart"
repository: public.ecr.aws/g2n4p2m7/margo
```

### Validate the application description

```bash
margot verify
```

Validates `app.yaml` (or `app.yaml.jinja`, rendered on the fly) against the upstream
Margo spec schema — no network access, no prior build required.

### Inspect it visually

```bash
margot describe
```

Renders the descriptor as structured panels and trees: identity, deployment profiles,
configuration (settings, schemas, parameters), and extensions.

### Build and push

```bash
margot build
margot push
```

`build` renders the descriptor and stages it under `build_dir`. `push` publishes the
artifact via [ORAS](https://oras.land/) to the registry declared in `margo.yaml`,
tagged with `version`:

```
public.ecr.aws/g2n4p2m7/margo:1.0.0
```

Log in first if the registry requires auth:

```bash
margot auth login
```

### Pull and inspect a published artifact

```bash
margot pull public.ecr.aws/g2n4p2m7/margo:1.0.0 --output ./out
margot fetch public.ecr.aws/g2n4p2m7/margo:1.0.0
```

`pull` writes the artifact's layers to disk as-is (no extraction). `fetch` prints the
raw manifest JSON for a quick remote inspection, without pulling anything.

### Shell completion

Enable shell tab completion for margot commands and flags:

```bash
# Quick setup — appends to your shell's rc file directly
margot --install-completion

# Manual setup — prints the script; redirect it wherever you source completions from
margot --show-completion bash > ~/.local/share/bash-completion/completions/margot
```

Both methods require a shell restart or re-sourcing the rc file to take effect.
`--show-completion` takes a shell argument (`bash`, `zsh`, `fish`, `powershell`, or `pwsh`)
and prints the completion script to stdout.

`--install-completion` has no `--path` option — it always appends to the shell's default rc file (e.g. `~/.bashrc`).
If you curate your own rc includes rather than a raw rc append, use
`--show-completion` instead and redirect the output to your preferred location.

## Learn more

- [Documentation](https://karnarokepoch.github.io/margot/) — full command reference,
  `margo.yaml` reference, configuration, and worked examples (Helm, Compose, Quadlet, multi-component).
- [ROADMAP.md](ROADMAP.md) — planned features, fixes, and ideas.
- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, testing, release process.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — community standards.

## License

[Apache License 2.0](LICENSE)
