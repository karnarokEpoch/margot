# margot package

Bundle already-built Margo application artifacts into a self-contained `.tgz` for
offline deployment in disconnected environments.

```
margot package [-t margo|compose|quadlet] [--project-dir PATH]
               [--build-dir DIR] [--output PATH] [--no-images]
```

!!! warning
    By default, `margot package` contacts an image registry to embed container images
    into the bundle. This requires registry access and valid credentials when your project
    has compose or quadlet components with an `image: {search, replace}` configuration.
    Use `--no-images` to skip image retrieval entirely and produce a network-free bundle.

## Prerequisites

Artifacts must be built first. Run [`margot build`](build.md) before packaging.
`package` never triggers a build itself — if the expected build output is missing,
it fails and tells you to run `margot build` first.

## Flags

| Flag | Default | Description |
|---|---|---|
| `--type` / `-t` | bundle all found types | Component type to include: `margo`, `compose`, or `quadlet`. Repeatable — pass once per type to select a subset. Omit to bundle every type that was built. |
| `--project-dir` | `.` | Project root directory (where `margo.yaml` lives). |
| `--build-dir` | `.dist` | Directory containing built artifacts. |
| `--output` | `.dist/<version>/<id>-<version>.tgz` | Override the output bundle path. |
| `--no-images` | off | Skip image retrieval. No registry access, no `images/` folder. Use this for fully offline/no-network packaging. |

## What it does

`package` collects already-built outputs from `.dist/<version>/` and packs them into one
`.tgz` file ready to hand off to an offline deployment target.

By default, `package` also discovers container image references from the built compose and
quadlet component archives and pulls them into the bundle as OCI image-layout tar archives
under `images/`. This makes the bundle fully self-contained for offline loading — no
registry access is required at deploy time. This step requires network access and registry
credentials for any eligible images.

Pass `--no-images` to skip image retrieval entirely: no registry contact, no credential
check, no `images/` folder. The bundle is then a plain local archive, identical to what
`package` produced before image inclusion was added.

The bundle is named `<id>-<version>.tgz`, where `<id>` is the `id` field from
`margo.yaml` and `<version>` is its `version` field. Both the archive filename and its
internal root directory use `id`, not `name`.

## Container image inclusion

Images are eligible for inclusion when a compose or quadlet component (or variant) has an
`image: {search, replace}` block in `margo.yaml`. The actual rendered image references are
discovered from the already-built component archives — the `replace` value already written
into the built content is what gets pulled, with no re-rendering of `margo.yaml`.

For each eligible image reference:

1. Registry credentials are checked before any manifest pull.
2. The image manifest (or multi-platform image index) is fetched via the existing OCI
   client.
3. Duplicate image references across components are deduplicated — each distinct reference
   is pulled once.
4. The image blobs are assembled into an OCI image-layout tar archive
   (`oci-layout` + `index.json` + `blobs/sha256/...`) under `images/` in the bundle.
5. Both single-manifest images and multi-platform image indexes are supported; by default
   all advertised platforms are included.

Runtime lookup and per-platform filtering are not currently configurable.

## Archive format

```
<id>-<version>.tgz
└── <id>-<version>/
    ├── app.yaml                          # margo build output, copied verbatim
    ├── resources/                        # any subdirectories inside margo/ are preserved
    │   └── description.md
    ├── images/                           # present by default, absent with --no-images
    │   └── <image-ref>.tar              # OCI image-layout tar per distinct image reference
    ├── <repo-path>/                      # compose component's resolved repository path
    │   └── <name>-<version>.tgz         # compose tarball, copied verbatim
    └── <repo-path>/                      # quadlet component's resolved repository path
        └── <name>-<version>.tgz         # quadlet tarball, copied verbatim
```

The top-level `margo/` wrapper directory from the build output is dropped; everything
inside it (`app.yaml`, `resources/`, etc.) lands directly at the bundle root.

Each component's folder path inside the bundle is the component's resolved `repository`
string from `margo.yaml`, with the registry hostname stripped. For example, a component
with `repository: public.ecr.aws/g2n4p2m7/margo` maps to `g2n4p2m7/margo/` inside the
bundle. A component-level `repository:` override takes precedence over the global
top-level `repository:` field — the same resolution order `push` uses.

Component tarballs (`<name>-<version>.tgz`) are copied in verbatim. They are never
re-extracted or re-tarred.

## `-t` filter and skip/fail semantics

**No `-t` (default):** bundles every type for which a build output exists on disk —
margo (always present), plus compose and/or quadlet if built.

**Explicit `-t`:** includes only the requested type(s). Two distinct failure modes apply:

- If the requested type is not defined in `margo.yaml` at all, `package` fails:
  > `compose component not defined in margo.yaml`

- If the requested type is defined in `margo.yaml` but its build output is missing from
  disk, `package` fails:
  > `Built compose artifact not found in .dist/<version>. Run 'margot build' first.`

The second error means the type is valid but hasn't been built yet — run
`margot build -t <type>` first.

## Collision guard

Before writing anything, `package` checks whether two components would resolve to the
same `(repository-folder, filename)` pair inside the bundle. If detected, it fails
without writing any partial output:

> `Collision: compose and quadlet would both write <repo>/<filename> to the bundle.`
> `Resolve the conflict in margo.yaml by using different repository values for each component.`

This guards against a known pre-existing condition where building compose and quadlet at
the same version into the same repository produces identically named files on disk.

## `--output` override

By default the bundle is written to `.dist/<version>/<id>-<version>.tgz`. Pass
`--output` to write it anywhere:

```bash
margot package --output /tmp/release/com-example-nginx-1.0.0.tgz
```

Parent directories are created automatically.

## Never pushed

A bundle has no OCI `artifactType` and carries no OCI manifest. `margot push` rejects
`PackageType.BUNDLE` the same way it rejects unknown types — a bundle is a local file
handoff only and is never uploaded to a registry.

The `images/` folder inside a bundle holds OCI image-layout tar archives. After extracting
the bundle, these can be loaded into a container runtime to enable fully offline deployment.
No specific runtime command is documented here because load syntax varies by tool version
and context; consult your runtime's documentation for the appropriate `load` command for
OCI image layout archives.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Bundle created successfully. |
| 1 | `margo.yaml` missing, build output missing, requested type not defined, collision detected, or invalid tag. |

## Common errors

- **`Built margo artifact not found at .dist/<version>/margo. Run 'margot build' first.`** — run `margot build` (or `margot build -t margo`) first.
- **`compose component not defined in margo.yaml`** — the requested type is not declared in your project descriptor.
- **`Built compose artifact not found in .dist/<version>. Run 'margot build' first.`** — the type is declared but not yet built.
- **`Collision: compose and quadlet would both write ...`** — two components resolve to the same folder and filename inside the bundle. Set distinct `repository:` values for each component in `margo.yaml`.

## Example

Given a project `margo.yaml`:

```yaml
apiVersion: v1
id: com-example-nginx
name: nginx
version: "1.0.0"
appVersion: "1.27.0"
description: "NGINX web server"
repository: public.ecr.aws/g2n4p2m7/margo
```

Build and bundle everything (pulls eligible images by default):

```bash
margot build
margot package
```

Produces `.dist/1.0.0/com-example-nginx-1.0.0.tgz` with this structure:

```
com-example-nginx-1.0.0.tgz
└── com-example-nginx-1.0.0/
    ├── app.yaml
    ├── images/
    │   └── <image-ref>.tar
    └── g2n4p2m7/margo/
        └── nginx-1.0.0.tgz
```

Bundle without image retrieval (fully offline/no-network):

```bash
margot build
margot package --no-images
```

Bundle only a specific component type:

```bash
margot package -t compose
```

Override the output path:

```bash
margot package --output ./releases/com-example-nginx-1.0.0.tgz
```
