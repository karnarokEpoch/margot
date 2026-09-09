# Getting Started

This guide takes you from installation to a complete round trip: install margot, write a
minimal project, validate and build it, publish it to a registry, and retrieve it back.

## Install

### From PyPI

```bash
pip install margo-tooling
```

### With uv

```bash
uv tool install margo-tooling
```

### With pipx

```bash
pipx install margo-tooling
```

### With a container

Every release publishes a container image to GHCR. Mount your project directory into
`/workspace`:

```bash
podman run --rm -v "$PWD":/workspace ghcr.io/karnarokepoch/margot:latest --help
```

Pin to a specific version instead of `latest` for reproducible builds:

```bash
podman run --rm -v "$PWD":/workspace ghcr.io/karnarokepoch/margot:1.0.0 --help
```

### From source

```bash
git clone https://github.com/karnarokEpoch/margot.git
cd margot
uv sync
```

## Minimal project

A Margo project is described by a `margo.yaml` file at the root, alongside your
application descriptor in `margo/app.yaml` (or `margo/app.yaml.jinja`). See
[Concepts — Project layout](../concepts.md#project-layout) for the full directory tree.

A minimal `margo.yaml`:

```yaml
apiVersion: v1
id: com-example-nginx
name: nginx
version: "1.0.0"
appVersion: "1.27.0"
description: "NGINX web server"
repository: public.ecr.aws/g2n4p2m7/margo
```

Place this at the root of your project. The `id` is the stable machine identifier for
the application — it should not change across releases. `version` becomes the OCI tag.

## Validate the descriptor

Before building, check that your `app.yaml` is valid against the Margo spec schema:

```bash
margot verify
```

margot reads `margo.yaml`, locates `margo/app.yaml` (or renders `margo/app.yaml.jinja`
on the fly if you use Jinja2 templating), and validates it against the vendored Margo
spec schema. No network access, no prior build required.

For stricter checks, also run margot's curated recommended schema:

```bash
margot verify --recommend
```

See [`margot verify`](../commands/verify.md) for the full flag reference and the
Schema A / Schema B behaviour matrix.

## Build locally

Once the descriptor validates, build the artifact into a local staging directory:

```bash
margot build
```

By default this builds the `margo` artifact type. To build compose or quadlet components,
or everything at once:

```bash
margot build --type compose
margot build --type all
```

Output goes to `.dist/` by default. See [`margot build`](../commands/build.md) for
`--build-dir`, `--variant`, and other options.

## Publish to a registry

Push the built artifact to the OCI registry declared in `margo.yaml`:

```bash
margot push
```

margot requires valid registry credentials before pushing. Log in first:

```bash
margot auth login public.ecr.aws --username AWS --password-stdin
```

See [Authentication](authentication.md) for a full walkthrough, including AWS ECR token
retrieval. See [`margot auth`](../commands/auth.md) for the flag reference.

Before a real push, you can verify your credentials and registry access without uploading
anything:

```bash
margot push --dry-run
```

The dry run performs the same checks as a real push (tag validation, built-artifact
on-disk check, credential expiry) plus a live write-access probe against the registry —
no artifact content is ever inspected or uploaded. See [`margot push`](../commands/push.md)
for details.

On success:

```
Pushed: public.ecr.aws/g2n4p2m7/margo:1.0.0
```

## Retrieve and inspect

Pull the artifact layers to disk (no extraction — `.tgz` blobs are written as-is):

```bash
margot pull public.ecr.aws/g2n4p2m7/margo:1.0.0 --output ./out
```

Fetch the raw manifest JSON for a quick remote inspection without downloading any layers:

```bash
margot fetch public.ecr.aws/g2n4p2m7/margo:1.0.0
```

`pull` and `fetch` work anonymously — no authentication required.

See [`margot pull`](../commands/pull.md) and [`margot fetch`](../commands/fetch.md) for
the full reference, including `--recursive` for pulling a margo artifact along with all
its declared components.

## Shell completion

Enable shell tab completion for margot commands and flags:

```bash
# Quick setup — appends to your shell's rc file directly
margot --install-completion

# Manual setup — prints the script; redirect it wherever you source completions from
margot --show-completion bash > ~/.local/share/bash-completion/completions/margot
```

Both methods require a shell restart or re-sourcing the rc file to take effect.
`--show-completion` takes a shell argument (`bash`, `zsh`, `fish`, `powershell`, or
`pwsh`) and prints the completion script to stdout.

!!! note
    `--install-completion` has no `--path` option — it always appends to the shell's
    default rc file (e.g. `~/.bashrc`). If you curate your own rc includes rather than
    a raw rc append, use `--show-completion` instead and redirect the output to your
    preferred location.
