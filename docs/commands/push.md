# margot push

Push built Margo application artifacts to an OCI registry.

```text
margot push [--type margo|compose|quadlet|all] [--project-dir PATH]
            [--registry REG] [--repository REPO] [--build-dir DIR]
            [--variant VARIANT] [--dry-run]
```

## Prerequisites

- Artifacts must be built first. Run [`margot build`](build.md) before pushing.
- Registry credentials must be active. Run [`margot auth login`](auth.md) if needed.
- The version tag must be valid SemVer. `push` validates this before doing anything else.

## Registry authentication

### Basic authentication

Registries that use HTTP Basic auth (RFC 7617) — such as a self-hosted zot or a
`registry:2` image with htpasswd — are supported. Log in once, then push works without
extra steps:

```bash
margot auth login 127.0.0.1:15000
margot push --registry 127.0.0.1:15000
```

margot answers the Basic challenge automatically. The first request to a fresh session
may take a few seconds if the registry delays unauthenticated responses.

Missing or rejected credentials exit 4 with a `margot auth login <host>` hint.

### Private CA

margot uses Python `requests` for registry HTTP. The CA set is `REQUESTS_CA_BUNDLE` or
`CURL_CA_BUNDLE` if either is set, otherwise the bundled `certifi` store. For a registry
served with a private or self-signed CA:

```bash
REQUESTS_CA_BUNDLE=./ca.crt margot push --registry 127.0.0.1:15000 ...
```

## Flags

| Flag            | Default                    | Description                                                    |
| --------------- | -------------------------- | -------------------------------------------------------------- |
| `--type`        | `all`                      | Package type to push: `margo`, `compose`, `quadlet`, or `all`. |
| `--project-dir` | `.`                        | Project root directory (where `margo.yaml` lives).             |
| `--registry`    | from config / `margo.yaml` | OCI registry hostname.                                         |
| `--repository`  | from config / `margo.yaml` | OCI repository path.                                           |
| `--build-dir`   | from config                | Directory containing built artifacts.                          |
| `--variant`     | all variants               | Variant to push: a variant name, or `all`.                     |
| `--dry-run`     | off                        | Validate and probe the registry without uploading anything.    |

## Dry run

`--dry-run` validates that a push would succeed without pushing any artifact content.

It runs the same checks as a real push — SemVer validation, built-artifact-exists-on-disk
check, and local credential-expiry check — plus one additional check: a live **write-access
probe** against the registry.

The probe opens an OCI blob-upload session (`POST /v2/<repository>/blobs/uploads/`) with the
resolved credentials. No content is sent:

- `202 Accepted` → write access confirmed. The upload session is immediately cancelled.
- `401` / `403` → no write access. Error, exit 4.
- Any other status → the registry error is reported with the status code and URL, exit 4.

The probe runs once per unique `(registry, repository)` pair per invocation — a single
`--type all --variant all` push against components sharing one repository opens one probe,
not one per variant.

On success, each target is reported:

```text
Dry run OK: public.ecr.aws/g2n4p2m7/margo:1.0.0
Dry run OK (simple): public.ecr.aws/g2n4p2m7/margo:1.0.0_compose-simple
```

## Output

A real push (no `--dry-run`) reports each pushed target:

```text
Pushed: public.ecr.aws/g2n4p2m7/margo:1.0.0
Pushed (simple): public.ecr.aws/g2n4p2m7/margo:1.0.0_compose-simple
```

## OCI media types

### margo artifact

Manifest `artifactType`: `application/vnd.margo.app.v1+json`

The descriptor is always the first layer:

| Layer      | Media type                                      |
| ---------- | ----------------------------------------------- |
| `app.yaml` | `application/vnd.margo.app.description.v1+yaml` |

#### Resource file discovery

Resource layers are discovered in two steps:

1. **Referenced files** — the `app.yaml` fields `metadata.catalog.application.icon`,
    `.descriptionFile`, `.licenseFile`, and `.releaseNotes` (paths relative to the margo build dir,
    any extension, a leading `./` is ignored). Each found file is pushed with a semantically typed
    media type. A value that is an `http://` or `https://` URL is not a local file: it is left
    as-is in the descriptor and nothing is pushed or warned for it.
2. **Extra files** — any other file under `resources/` (including sub-folders) not already pushed
    in step 1, each with `application/octet-stream`.

A referenced file is pushed exactly once. If a field is set but the file is missing from the
build output, margot emits a warning to stderr and continues — the push is not blocked:

```text
'icon' references 'resources/icon.svg' but the file was not found; skipping.
```

#### Media types for referenced files

| `app.yaml` field  | Media type template                                     |
| ----------------- | ------------------------------------------------------- |
| `icon`            | `application/vnd.margo.app.icon.v1+{format}`            |
| `descriptionFile` | `application/vnd.margo.app.descriptionFile.v1+{format}` |
| `licenseFile`     | `application/vnd.margo.app.licenseFile.v1+{format}`     |
| `releaseNotes`    | `application/vnd.margo.app.releaseNotes.v1+{format}`    |

#### `{format}` token

Derived from the file extension, following the Margo spec
([Application Registry](https://docs.margo.org/specification/applications/application-registry)):

| Extension(s)        | Token                              |
| ------------------- | ---------------------------------- |
| `jpg`, `jpeg`       | `jpeg`                             |
| `tif`, `tiff`       | `tiff`                             |
| `md`, `markdown`    | `markdown`                         |
| any other extension | lowercased as-is (`svg`, `png`, …) |
| (no extension)      | `bin`                              |

Examples:

| File                         | Field          | Media type                                           |
| ---------------------------- | -------------- | ---------------------------------------------------- |
| `resources/icon.svg`         | `icon`         | `application/vnd.margo.app.icon.v1+svg`              |
| `resources/photo.JPG`        | `icon`         | `application/vnd.margo.app.icon.v1+jpeg`             |
| `resources/release-notes.md` | `releaseNotes` | `application/vnd.margo.app.releaseNotes.v1+markdown` |
| `resources/license.txt`      | `licenseFile`  | `application/vnd.margo.app.licenseFile.v1+txt`       |

#### Layer annotations

Every resource layer (referenced and extra) carries both annotations.
The descriptor layer (`app.yaml`) does not carry `org.margo.app.resource`.

| Annotation                       | Value                                                                    |
| -------------------------------- | ------------------------------------------------------------------------ |
| `org.opencontainers.image.title` | path relative to the margo build dir, e.g. `resources/screenshots/a.png` |
| `org.margo.app.resource`         | `"true"`                                                                 |

### compose / quadlet artifact

| Layer                  | Media type                                                       |
| ---------------------- | ---------------------------------------------------------------- |
| `<name>-<version>.tgz` | `application/vnd.org.margo.component.compose.tar+gzip` (compose) |
| `<name>-<version>.tgz` | `application/vnd.org.margo.component.quadlet.tar+gzip` (quadlet) |

Manifest `artifactType`: `application/vnd.org.margo.component.compose+json` / `application/vnd.org.margo.component.quadlet+json`

Annotations pushed with compose/quadlet:

| Annotation                             | Value                   |
| -------------------------------------- | ----------------------- |
| `org.margo.component.type`             | `compose` or `quadlet`  |
| `org.margo.component.version`          | OCI tag                 |
| `org.opencontainers.image.title`       | application name        |
| `org.opencontainers.image.description` | application description |

## Exit codes

| Code | Meaning                                                                                                                                                                                              |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | All artifacts pushed (or dry run passed).                                                                                                                                                            |
| 1    | Unexpected failure.                                                                                                                                                                                  |
| 2    | Invalid flag value detected before any work begins (e.g. unknown `--type`).                                                                                                                          |
| 3    | SemVer validation failed, or a required artifact was not found on disk.                                                                                                                              |
| 4    | Registry or authentication failure: credentials missing, expired, or rejected, no write access (dry run), or an HTTP error status from the registry such as 429, or a 5xx or 404 on an upload. |

## Common errors

- **`Credentials expired`** — run `margot auth login public.ecr.aws`.
- **`Registry requires authentication`** — run `margot auth login <host>`.
- **`Registry rejected the stored credentials`** — run `margot auth login <host>` to replace them.
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
