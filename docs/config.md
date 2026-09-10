# Configuration

margot resolves configuration from four sources, highest to lowest priority:

1. **CLI flags** — always win
2. **Environment variables** — `MARGOT_` prefix, e.g. `MARGOT_REGISTRY`
3. **`margot.toml`** in the project directory
4. **`~/.config/margot/config.toml`** — user-level defaults

## Config keys

| Key | Description | Example |
|---|---|---|
| `registry` | OCI registry base URL | `public.ecr.aws` |
| `repository` | OCI repository path | `g2n4p2m7/margo` |
| `build_dir` | Local build output directory | `.dist` |
| `run_dir` | Local pull output directory | `.run` |

## margot.toml example

Place `margot.toml` at the project root alongside `margo.yaml`:

```toml
registry = "public.ecr.aws"
repository = "g2n4p2m7/margo"
build_dir = ".dist"
run_dir = ".run"
```

## Environment variables

Every config key is available as an environment variable with the `MARGOT_` prefix:

```bash
export MARGOT_REGISTRY=public.ecr.aws
export MARGOT_REPOSITORY=g2n4p2m7/margo
export MARGOT_BUILD_DIR=.dist
```

## Per-project vs user defaults

`margot.toml` in the project directory is for project-specific defaults (committed to the
repository). `~/.config/margot/config.toml` is for personal user defaults that apply
across projects.

CLI flags and environment variables always override both config files.

## Credential expiry

Credential expiry state is tracked separately in `~/.config/margot/credentials.toml`.
See [`margot auth login`](commands/auth.md) for details.
