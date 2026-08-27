# margot

**margot** is a developer CLI for building and publishing Margo application packages as OCI artifacts. It handles
packaging, tagging, and pushing/pulling to any OCI-compliant registry.

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

A Margo project is described by a `margo.yaml` file at the project root. margot reads it to build and push your
application to a registry, e.g.:

```text
public.ecr.aws/g2n4p2m7/margo:1.0.0
```

## Learn more

- [GitHub repository](https://github.com/karnarokEpoch/margot)
- [PyPI package](https://pypi.org/project/margo-tooling/)
