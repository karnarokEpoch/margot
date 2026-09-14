# margot push

Push built Margo application artifacts to an OCI registry.

```
margot push [--type margo|compose|quadlet|all] [--project-dir PATH]
            [--registry REG] [--repository REPO] [--build-dir DIR]
            [--variant VARIANT] [--dry-run]
```

## Prerequisites

- Artifacts must be built first. Run [`margot build`](build.md) before pushing.
- Registry credentials must be active. Run [`margot auth login`](auth.md) if needed.
- The version tag must be valid SemVer. `push` validates this before doing anything else.

## Flags

| Flag | Default | Description |
|---|---|---|
| `--type` | `all` | Package type to push: `margo`, `compose`, `quadlet`, or `all`. |
| `--project-dir` | `.` | Project root directory (where `margo.yaml` lives). |
| `--registry` | from config / `margo.yaml` | OCI registry hostname. |
| `--repository` | from config / `margo.yaml` | OCI repository path. |
| `--build-dir` | from config | Directory containing built artifacts. |
| `--variant` | all variants | Variant to push: a variant name, or `all`. |
| `--dry-run` | off | Validate and probe the registry without uploading anything. |

## Dry run

`--dry-run` validates that a push would succeed without pushing any artifact content.

It runs the same checks as a real push — SemVer validation, built-artifact-exists-on-disk
check, and local credential-expiry check — plus one additional check: a live **write-access
probe** against the registry.

The probe opens an OCI blob-upload session (`POST /v2/<repository>/blobs/uploads/`) with the
resolved credentials. No content is sent:

- `202 Accepted` → write access confirmed. The upload session is immediately cancelled.
- `401` / `403` → no write access. Error, exit 1.
- Any other status → surfaced as-is, exit 1.

The probe runs once per unique `(registry, repository)` pair per invocation — a single
`--type all --variant all` push against components sharing one repository opens one probe,
not one per variant.

On success, each target is reported:

```
Dry run OK: public.ecr.aws/g2n4p2m7/margo:1.0.0
Dry run OK (simple): public.ecr.aws/g2n4p2m7/margo:1.0.0_compose-simple
```

## Output

A real push (no `--dry-run`) reports each pushed target:

```
Pushed: public.ecr.aws/g2n4p2m7/margo:1.0.0
Pushed (simple): public.ecr.aws/g2n4p2m7/margo:1.0.0_compose-simple
```

## OCI media types

### margo artifact

| Layer | Media type |
|---|---|
| `app.yaml` | `application/vnd.margo.app.description.v1+yaml` |
| `resources/icon.png` | `application/vnd.margo.app.icon.v1+png` |
| `resources/license.txt` | `application/vnd.margo.app.license.v1+plain` |
| `resources/release-notes.md` | `application/vnd.margo.app.releaseNotes.v1+markdown` |
| `resources/description.md` | `application/vnd.margo.app.descriptionFile.v1+markdown` |

Manifest `artifactType`: `application/vnd.margo.app.v1+json`

### compose / quadlet artifact

| Layer | Media type |
|---|---|
| `<name>-<version>.tgz` | `application/vnd.org.margo.component.compose.tar+gzip` (compose) |
| `<name>-<version>.tgz` | `application/vnd.org.margo.component.quadlet.tar+gzip` (quadlet) |

Manifest `artifactType`: `application/vnd.org.margo.component.compose+json` / `application/vnd.org.margo.component.quadlet+json`

Annotations pushed with compose/quadlet:

| Annotation | Value |
|---|---|
| `org.margo.component.type` | `compose` or `quadlet` |
| `org.margo.component.version` | OCI tag |
| `org.opencontainers.image.title` | application name |
| `org.opencontainers.image.description` | application description |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All artifacts pushed (or dry run passed). |
| 1 | SemVer validation failed, artifact not built, credentials expired, registry error, or no write access (dry run). |

## Common errors

- **`Credentials expired`** — run `margot auth login public.ecr.aws`.
- **`Invalid tag`** — version from `margo.yaml` or `--version` is not valid SemVer.
- **Artifact not found on disk** — run `margot build` first.

## Example

```bash
# Push everything
margot push

# Dry run — validate without uploading
margot push --dry-run

# Push only the margo artifact
margot push --type margo

# Push a single compose variant
margot push --type compose --variant simple

# Push to a different registry
margot push --registry public.ecr.aws --repository g2n4p2m7/margo
```
