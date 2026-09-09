# Concepts

## Package types

margot builds and publishes three package types, each producing a separate OCI artifact.

### margo

The Margo application description artifact. Contains the `app.yaml` descriptor and
optional supporting resources.

- **Source:** `margo/` directory (path set by top-level `directory` in `margo.yaml`, default: `margo`)
- **Output:** OCI artifact tagged with the top-level `version`
- **`artifactType`:** `application/vnd.margo.app.v1+json`

Layers and their media types:

| File | Media type |
|---|---|
| `app.yaml` | `application/vnd.margo.app.description.v1+yaml` |
| `resources/icon.png` | `application/vnd.margo.app.icon.v1+png` |
| `resources/license.txt` | `application/vnd.margo.app.license.v1+plain` |
| `resources/release-notes.md` | `application/vnd.margo.app.releaseNotes.v1+markdown` |
| `resources/description.md` | `application/vnd.margo.app.descriptionFile.v1+markdown` |

Build step: copy source → output dir, render `app.yaml` from `app.yaml.jinja` if present,
or copy `app.yaml` verbatim. Both files present is a hard error.

### compose

A Docker Compose deployment component.

- **Source:** `compose/` directory (path set by `compose.directory` in `margo.yaml`)
- **Output:** `.tgz` tarball, OCI artifact tagged with the variant's `version`
- **`artifactType`:** `application/vnd.org.margo.component.compose+json`
- **Layer media type:** `application/vnd.org.margo.component.compose.tar+gzip`

Build step: copy source dir → temp dir (respecting `.rsyncignore`), apply `image`
search/replace if declared, pack as `<name>-<version>.tgz` using pure Python
`tarfile` — no `tar` binary required.

Tarball structure: a single top-level `<name>/` directory wraps the contents, so
extracting produces `<name>/<file>`.

### quadlet

A systemd Quadlet deployment component.

- **Source:** `quadlet/` directory (path set by `quadlet.directory` in `margo.yaml`)
- **Output:** `.tgz` tarball, OCI artifact tagged with the variant's `version`
- **`artifactType`:** `application/vnd.org.margo.component.quadlet+json`
- **Layer media type:** `application/vnd.org.margo.component.quadlet.tar+gzip`

Build step and tarball structure: identical to compose.

## Tag naming

All tags are valid OCI tags. The artifact type (`margo`, `compose`, `quadlet`) is encoded
in the OCI `artifactType` field, not in the tag. Multiple artifacts at different tags can
coexist in the same repository.

!!! warning
    The `+` character (SemVer build metadata separator) is **not valid in OCI tags**.
    Write versions with `+` in `margo.yaml` — margot converts `+` to `_` automatically
    when producing OCI tags.

| Type | Tag format | Example |
|---|---|---|
| margo | `<version>` | `1.3.0` |
| compose (no variants) | `<version>` | `1.3.0` |
| compose (variant) | `<version>_<variant-derived>` | `1.3.0_compose-simple` |
| quadlet (no variants) | `<version>` | `1.3.0` |
| quadlet (variant) | `<version>_<variant-derived>` | `1.3.0_quadlet-simple` |

Variant tag derivation: when a variant has no explicit `version`, it is derived as
`<component-version>+<type>-<variant-name>` → OCI tag `<component-version>_<type>-<variant-name>`.

| `margo.yaml` version | OCI tag |
|---|---|
| `1.0.0+compose-default` | `1.0.0_compose-default` |
| `2.1.0+quadlet-minimal` | `2.1.0_quadlet-minimal` |

The suffix exists because multiple components and variants commonly share one OCI repository — the
top-level `repository` field in `margo.yaml` is inherited by compose and quadlet components and by
every variant unless explicitly overridden at the component or variant level. Within a single
repository, the tag is the only thing that distinguishes artifacts at the registry level: the OCI
`artifactType` field separates a margo artifact from a compose or quadlet artifact, but it does
**not** distinguish between different variants of the same type. Without the suffix, pushing
compose variant `default` at version `1.0.0` and variant `simple` also at version `1.0.0` into the
same repository would both resolve to tag `1.0.0` — the second push would silently overwrite the
first one's tag. The `_compose-default` / `_compose-simple` suffix is what keeps each variant
independently addressable.

## Project layout

A Margo application project that margot operates on:

```
<project-root>/
├── margo.yaml                     # project descriptor (required)
├── margo/                         # margo artifact source (default: margo/)
│   ├── app.yaml                   # Margo app descriptor — static
│   ├── app.yaml.jinja             # Margo app descriptor — Jinja2 template (use one, not both)
│   └── resources/                 # optional supporting files
│       ├── icon.png
│       ├── license.txt
│       ├── release-notes.md
│       └── description.md
├── compose/                       # compose source (default: compose/)
│   ├── compose.yaml               # flat layout — used when no variants declared
│   ├── .rsyncignore               # optional ignore patterns (flat layout)
│   ├── default/                   # 'default' variant subdir
│   │   ├── compose.yaml
│   │   └── .rsyncignore           # optional ignore patterns (per-variant)
│   ├── simple/
│   │   └── compose.yaml
│   └── addon-mosquitto/
│       └── compose.yaml
└── quadlet/                       # quadlet source (default: quadlet/)
    ├── myapp.container            # flat layout — used when no variants declared
    ├── default/
    │   └── myapp.container
    └── simple/
        └── myapp.container
```

### Flat layout vs variants

**Flat layout (no `variants` in `margo.yaml`):** the component directory root is used as
a single artifact, tagged with the component's `version`.

**Variants declared:** the `variants` list in `margo.yaml` is authoritative — only declared
variants are built. All variant names (including `default`) map to
`<component.directory>/<name>/`. There is no implicit root mapping.

### `.rsyncignore`

If `.rsyncignore` is present in a source dir (or variant subdir), its patterns are applied
during the tree copy step (via Python `shutil.copytree`). One file per source dir; applies
to that dir only.

## SemVer gate

SemVer validation applies to `build` and `push` only. `pull` and `fetch` retrieve arbitrary
existing artifacts and do not validate the tag format.
