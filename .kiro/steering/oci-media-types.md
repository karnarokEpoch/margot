---
inclusion: auto
description: >
  Reference for all OCI and Docker legacy media types used in this project.
  Use this when writing or reviewing test fixtures, manifest parsing, OCI push/pull logic,
  or any code that constructs or inspects manifest/config/layer fields.
  Ensures correct, consistent media type strings across the codebase and realistic test data.
---

# OCI Media Types Reference

## Manifest types (`manifest.mediaType`)

| Media type | Use |
|---|---|
| `application/vnd.oci.image.manifest.v1+json` | Single-arch image or artifact manifest |
| `application/vnd.oci.image.index.v1+json` | Multi-arch index (list of manifests) |
| `application/vnd.docker.distribution.manifest.v2+json` | Docker v2 manifest (legacy) |
| `application/vnd.docker.distribution.manifest.list.v2+json` | Docker multi-arch list (legacy) |

## Config blob types (`config.mediaType`)

| Media type | Use |
|---|---|
| `application/vnd.oci.empty.v1+json` | Scratch/empty config — canonical for pure artifacts |
| `application/vnd.oci.image.config.v1+json` | Standard container image config |
| `application/vnd.docker.container.image.v1+json` | Docker image config (legacy) |

## Layer types

| Media type | Use |
|---|---|
| `application/vnd.oci.image.layer.v1.tar+gzip` | Standard compressed layer |
| `application/vnd.oci.image.layer.v1.tar` | Uncompressed layer |
| `application/vnd.oci.image.layer.nondistributable.v1.tar+gzip` | Non-distributable layer |

## Margot-specific types

| Media type | Use |
|---|---|
| `application/vnd.margo.app.v1+json` | `artifactType` for Margo app artifacts |
| `application/vnd.margo.app.description.v1+yaml` | Layer: `app.yaml` application descriptor. Descriptor-layer lookup (remote `describe`/`verify`, `pull --recursive`) matches this `mediaType`, never the layer filename |
| `application/vnd.margo.app.icon.v1+{format}` | Layer: file referenced by the `icon` field |
| `application/vnd.margo.app.licenseFile.v1+{format}` | Layer: file referenced by the `licenseFile` field (spec name is `licenseFile`, not `license`) |
| `application/vnd.margo.app.releaseNotes.v1+{format}` | Layer: file referenced by the `releaseNotes` field |
| `application/vnd.margo.app.descriptionFile.v1+{format}` | Layer: file referenced by the `descriptionFile` field |
| `application/octet-stream` | Layer: any other file under `resources/` not referenced by one of the four fields above |

Templated types are built from the constants in `src/margot/domain/layers.py`
(`MARGO_*_MEDIA_TYPE_TEMPLATE`, `MARGO_RESOURCE_FALLBACK_MEDIA_TYPE`). `{format}` is the
spec's `{file format}` token, derived from the file's extension (lowercased, no dot) through
an explicit table:

| Extension | `{format}` |
|---|---|
| `jpg`, `jpeg` | `jpeg` |
| `tif`, `tiff` | `tiff` |
| `md`, `markdown` | `markdown` |
| any other (`png`, `svg`, `txt`, `bmp`, …) | the extension itself (`icon.SVG` → `…icon.v1+svg`, `license.txt` → `…licenseFile.v1+txt`) |
| none | `bin` |

Do not use the `mimetypes` module for this; it depends on host files and yields values such as
`svg+xml`. Source: [Margo Application Registry
spec](https://docs.margo.org/specification/applications/application-registry).

Resource layer annotations:

- `org.opencontainers.image.title` — path relative to the margo build directory, sub-folders
  included (e.g. `resources/screenshots/a.png`).
- `org.margo.app.resource` = `"true"` — required by the Margo spec on every layer that
  references an application resource (referenced files and generic extras). Not set on the
  descriptor, compose or quadlet layers. The spec does not define the value; margot uses
  `"true"`.
- Use the `MARGO_*` constants in code and tests; do not retype these strings.

## Notes

- For OCI artifacts, use `vnd.oci.empty.v1+json` as config + a custom `artifactType` — do not encode artifact type in the tag.
- Docker legacy types (`vnd.docker.*`) are read-only concerns — only needed when parsing manifests from registries that haven't migrated to OCI spec.
- In test fixtures (`conftest.py`), use `application/vnd.oci.image.manifest.v1+json` as the manifest `mediaType`.
