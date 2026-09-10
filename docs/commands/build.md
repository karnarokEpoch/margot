# margot build

Build Margo application package types locally into `build_dir`.

```
margot build [--type margo|compose|quadlet|all] [--project-dir PATH]
             [--version VERSION] [--build-dir DIR] [--variant VARIANT]
```

## Flags

| Flag | Default | Description |
|---|---|---|
| `--type` | `all` | Package type to build: `margo`, `compose`, `quadlet`, or `all`. |
| `--project-dir` | `.` | Project root directory (where `margo.yaml` lives). |
| `--version` | from `margo.yaml` | Override the version for the selected type. |
| `--build-dir` | from config | Output directory for built artifacts. |
| `--variant` | all variants | Variant to build: a variant name, or `all`. Only meaningful for `compose` and `quadlet`. |

## What it does

`build` reads `margo.yaml`, copies sources, renders templates, and produces local artifacts
ready to push. Nothing is uploaded — use [`margot push`](push.md) afterward.

### `--type margo`

1. Read `margo.yaml` from the project directory.
2. Copy source `directory` → `<build_dir>/<version>/margo/` (pure Python, no rsync).
3. Render `app.yaml`:
   - Both `app.yaml.jinja` and `app.yaml` present → hard error (exit 1).
   - `app.yaml.jinja` present → render with Jinja2 `StrictUndefined`, write output as `app.yaml`. The `.jinja` source is not included in output.
   - `app.yaml.jinja` absent → copy `app.yaml` verbatim. No substitution.

### `--type compose` / `--type quadlet`

1. Read `margo.yaml`.
2. Copy source dir → temp dir (respecting `.rsyncignore` if present in source dir).
3. Substitute placeholders in all text files (registry/repo URL, image tags).
4. Apply the component/variant's `image` search/replace if declared in `margo.yaml`.
5. Pack as `<build_dir>/<version>/<name>-<version>.tgz` (pure Python `tarfile`, no `tar` binary).

Variant handling:

- `--variant all` → build every variant declared in `margo.yaml`.
- `--variant NAME` → build the single named variant only.
- No `--variant` → same as `all`.

### `--type all`

Runs `margo` + `compose` (all variants) + `quadlet` (all variants) in sequence.

## Tag naming

All tags produced by `build` are valid OCI tags. The `+` character (SemVer build metadata)
is converted to `_` in OCI tags automatically:

| Type | Tag format | Example |
|---|---|---|
| margo | `<version>` | `1.3.0` |
| compose (flat) | `<version>` | `1.3.0` |
| compose (variant) | `<version>_<variant>` | `1.3.0_simple` |
| quadlet (flat) | `<version>` | `1.3.0` |
| quadlet (variant) | `<version>_<variant>` | `1.3.0_simple` |

The artifact type (`margo`, `compose`, `quadlet`) is encoded in the OCI `artifactType` field, not in
the tag. Multiple artifacts at different tags can coexist in the same repository.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Build succeeded. |
| 1 | `margo.yaml` missing, template error, both `app.yaml` and `app.yaml.jinja` present, invalid tag, or any other build failure. |

## Common errors

- **`margo.yaml not found in current directory. Run margot init or create it manually.`** — run from the project root, or pass `--project-dir`.
- **Both `app.yaml` and `app.yaml.jinja` present** — remove one. margot refuses to guess which is canonical.
- **Unresolved Jinja2 variable** — check the template variable name against the [template context](../margo-yaml.md#template-context).

## Example

```bash
# Build everything (margo + all compose/quadlet variants)
margot build

# Build only the margo artifact
margot build --type margo

# Build a single compose variant
margot build --type compose --variant simple

# Build into a custom output directory
margot build --build-dir .artifacts
```
