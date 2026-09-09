# margot pull

Pull OCI artifact layers to a local directory without extraction.

```
margot pull <uri> [--output DIR] [--recursive]
```

## Arguments

| Argument | Description |
|---|---|
| `<uri>` | Full OCI reference: `registry/repository:tag`. Example: `public.ecr.aws/g2n4p2m7/margo:1.0.0` |

## Flags

| Flag | Default | Description |
|---|---|---|
| `--output` / `-o` | `.` (current directory) | Directory to write pulled layers into. |
| `--recursive` / `-r` | off | Pull declared components too (margo artifacts only). |

## What it does

`pull` fetches and writes artifact layers to disk exactly as stored — no extraction, no
modification. `.tgz` blobs land as `.tgz` files.

No SemVer validation: `pull` retrieves arbitrary existing artifacts. Auth: anonymous only
(no `margot auth login` required for public registries).

### Logic

1. Validate the URI format.
2. Fetch the manifest.
3. Detect artifact type from the `artifactType` manifest field:
   - `application/vnd.margo.app.v1+json` → margo
   - `application/vnd.org.margo.component.compose+json` → compose
   - `application/vnd.org.margo.component.quadlet+json` → quadlet
   - anything else → unknown
4. Pull all layers to `--output`.
5. For compose/quadlet: rename the payload file using the layer's
   `org.opencontainers.image.title` annotation, or `<title>-<version>.tgz` from manifest
   annotations, when available.
6. Report each written file path.

## Recursive pull (`--recursive`)

Only applies to margo artifacts. Has no effect on compose, quadlet, or unknown artifacts.

When `--recursive` is set for a margo artifact:

1. Locate `app.yaml` in the pulled layers.
2. Parse `deploymentProfiles[].components[]` to extract component OCI references:
   `properties.repository` (strip `oci://` scheme) + `properties.revision` → OCI ref.
   Components missing either field are skipped with a warning.
3. Deduplicate by `(repository, tag)`, preserving first-seen order.
4. Pull each component into `--output/<component-name>/`.

If `app.yaml` cannot be found, parsed, or a component pull fails, a warning is logged but
the root pull succeeds.

### Recursive output structure

```
outdir/
  app.yaml
  database/
    postgres-14.0.0.tgz
  cache/
    redis-7.0.0.tgz
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Pull succeeded (including partial recursive pulls with component warnings). |
| 1 | Invalid URI, manifest fetch failed, or registry error. |

## Example

```bash
# Pull a margo artifact to the current directory
margot pull public.ecr.aws/g2n4p2m7/margo:1.0.0

# Pull into a specific directory
margot pull public.ecr.aws/g2n4p2m7/margo:1.0.0 --output ./out

# Pull a margo artifact and all its declared components
margot pull public.ecr.aws/g2n4p2m7/margo:1.0.0 --output ./out --recursive

# Pull a compose component
margot pull public.ecr.aws/g2n4p2m7/margo:1.0.0_compose-default --output ./components
```
