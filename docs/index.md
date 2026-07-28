# margot

**margot** is a developer CLI for building and publishing Margo application packages as OCI artifacts. It handles
packaging, tagging, and pushing/pulling to any OCI-compliant registry.

## Install

margot isn't published to PyPI yet. Install it from source with [uv](https://docs.astral.sh/uv/):

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
