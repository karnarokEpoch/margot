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
| `application/vnd.margo.app.description.v1+yaml` | Layer: `margo.yaml` descriptor |

## Notes

- For OCI artifacts, use `vnd.oci.empty.v1+json` as config + a custom `artifactType` — do not encode artifact type in the tag.
- Docker legacy types (`vnd.docker.*`) are read-only concerns — only needed when parsing manifests from registries that haven't migrated to OCI spec.
- In test fixtures (`conftest.py`), use `application/vnd.oci.image.manifest.v1+json` as the manifest `mediaType`.
