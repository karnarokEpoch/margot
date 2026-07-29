# margo.yaml

`margo.yaml` is the project descriptor file for a Margo application. It lives at the project root and is the single
source of truth read by `margot build` and `margot push`.

```yaml
apiVersion: v1
name: myapp
appVersion: "1.0.0"
description: "Human-readable description of the application"
annotations:
  opentelemetry.io/instrumented: "true"
maintainers:
  - name: Alice Example
    email: alice@example.com

margo:
  directory: margo
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo

compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default
      version: 1.0.0
    - name: simple
      version: 1.0.0_simple
    - name: addon-mosquitto
      version: 1.0.0_addon-mosquitto

quadlet:
  directory: quadlet
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default
      version: 1.0.0
    - name: simple
      version: 1.0.0_simple
```

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `apiVersion` | Yes | Config schema version. Currently `v1`. |
| `name` | Yes | Application name. Used in tarball filenames (`<name>-<version>.tgz`) and OCI title annotation. |
| `appVersion` | No | Human-facing application version. Not validated as SemVer. Used as the value for `<app_tag>` placeholder substitution. If absent, `<app_tag>` resolves to an empty string. |
| `description` | Yes | Short description. Used in OCI description annotation. |
| `annotations` | No | Arbitrary key/value pairs passed as OCI annotations. |
| `maintainers` | No | List of maintainers, each with `name` (required) and `email` (optional). |

## Components

A `margo.yaml` declares one or more **components** — each producing a separate OCI artifact when built. The three
component types are `margo`, `compose`, and `quadlet`.

Every component shares these fields:

| Field | Required | Description |
|-------|----------|-------------|
| `directory` | Yes | Path (relative to project root) to the component source directory. |
| `version` | Yes* | OCI tag for the artifact. Must be a valid OCI tag; SemVer recommended. Ignored when `variants` is present. |
| `repository` | No | OCI repository for this component. Overrides the global `repository` from tool config / CLI flag / env var. |

\* Required only when no `variants` are declared for that component.

### margo

The core Margo application descriptor artifact. Its source directory must contain `app.yaml` (with optional
`resources/` subdirectory). This component does not support variants.

### compose

A Docker Compose deployment artifact. Can be built as a single artifact (flat layout) or as multiple variant
artifacts.

### quadlet

A systemd Quadlet deployment artifact. Same structure and variant support as `compose`.

## Variants

Variants let you ship multiple deployment flavours from a single component. When `variants` is declared, each entry
maps to a subdirectory under the component's `directory`:

```yaml
compose:
  directory: compose
  variants:
    - name: default
      version: 1.0.0
    - name: simple
      version: 1.0.0_simple
```

This produces two artifacts built from `compose/default/` and `compose/simple/`.

Rules:

- `name: default` is a **reserved name** but not special — it maps to `<directory>/default/`, a real subdirectory like
  any other variant.
- When `variants` is present, the component-level `version` is ignored. Each variant carries its own `version`.
- `--variant all` builds every declared variant. `--variant NAME` selects one.

## Version strings and OCI tags

!!! warning
    The `+` character (SemVer build metadata separator) is **not valid in OCI tags**. Write versions with `+` in
    `margo.yaml` — margot automatically converts `+` to `_` when producing OCI tags.

For example:

| `margo.yaml` version | OCI tag pushed |
|-----------------------|----------------|
| `1.0.0+margo` | `1.0.0_margo` |
| `1.0.0+quadlet` | `1.0.0_quadlet` |
| `2.1.0+simple` | `2.1.0_simple` |

This is the standard way to prevent tag collisions when multiple components share the same repository — append
build metadata (`+margo`, `+quadlet`, `+compose`, variant name, etc.) to distinguish them.
