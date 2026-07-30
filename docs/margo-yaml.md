# margo.yaml

`margo.yaml` is the project descriptor file for a Margo application. It lives at the project root and is the single
source of truth read by `margot build` and `margot push`.

```yaml
apiVersion: v1
id: com-example-myapp
name: myapp
version: "1.0.0"
appVersion: "2.3.1"
description: "Human-readable description of the application"
annotations:
  opentelemetry.io/instrumented: "true"
author:
  - name: Alice Example
    email: alice@example.com
organization:
  - name: Example Corp
    site: https://example.com

margo:
  directory: margo
  version: 1.0.0+margo
  repository: public.ecr.aws/g2n4p2m7/margo

compose:
  directory: compose
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default
    - name: simple

quadlet:
  directory: quadlet
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default
    - name: simple
```

## Fields

| Field | Required | Description |
| ------- | ---------- | ------------- |
| `apiVersion` | Yes | Config schema version. Currently `v1`. |
| `id` | Yes | Margo application identifier. Lowercase letters, digits, and dashes only. Used as the base for derived component names and deployment profile IDs. |
| `name` | Yes | Application name. Used in tarball filenames (`<name>-<version>.tgz`) and OCI title annotation. |
| `version` | Yes | Manifest/package version (like Helm's chart version). Exposed as `manifest.version` in templates. |
| `appVersion` | No | Version of the deployed application (like Helm's `appVersion`). Not validated as SemVer. Exposed as `manifest.appVersion` in templates. Useful for passing as a parameter to deployment profiles (e.g. `image.tag`). |
| `description` | Yes | Short description. Used in OCI description annotation and exposed as `manifest.description` in templates. |
| `annotations` | No | Arbitrary key/value pairs passed as OCI annotations. |
| `author` | No | List of authors, each with `name` (optional) and `email` (optional). Maps to `metadata.catalog.author` in the Margo spec. |
| `organization` | No | List of organizations, each with `name` (required) and `site` (optional). Maps to `metadata.catalog.organization` in the Margo spec. |

## Components

A `margo.yaml` declares one or more **components** — each producing a separate OCI artifact when built. The three
component types are `margo`, `compose`, and `quadlet`.

Every component shares these fields:

| Field | Required | Description |
| ------- | ---------- | ------------- |
| `directory` | No | Path (relative to project root) to the component source directory. Default: component type name (`margo`, `compose`, `quadlet`). |
| `version` | Yes | Base version for the component. Used directly as OCI tag in flat mode; used as the derivation base for variant versions. |
| `repository` | No | OCI repository for this component. Overrides the global `repository` from tool config / CLI flag / env var. |
| `component` | No | Margo component name (developer-owned). Default: `<id>-<type>`. Flat mode only. |

### margo

The core Margo application descriptor artifact. Its source directory must contain either `app.yaml.jinja` (rendered
at build time) or `app.yaml` (copied verbatim). This component does not support variants.

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
  version: 2.1.0
  variants:
    - name: default
    - name: minimal
```

This produces two artifacts built from `compose/default/` and `compose/minimal/`.

### Variant fields

| Field | Required | Description |
| ------- | ---------- | ------------- |
| `name` | Yes | Variant name. Maps to `<directory>/<name>/` subdirectory. |
| `version` | No | Override the derived version. Default: `<component-version>+<type>-<variant-name>`. |
| `component` | No | Override the derived component name. Default: `<id>-<type>-<variant-name>`. |

With the example above (`version: 2.1.0`, compose variants `default` and `minimal`):

| Variant | Derived version | OCI tag |
|---------|-----------------|---------|
| default | `2.1.0+compose-default` | `2.1.0_compose-default` |
| minimal | `2.1.0+compose-minimal` | `2.1.0_compose-minimal` |

### Rules

- `name: default` is a **reserved name** but not special — it maps to `<directory>/default/`, a real subdirectory like
  any other variant.
- When `variants` is present, the component-level `version` is used as the derivation base, not as a direct OCI tag.
- `--variant all` builds every declared variant. `--variant NAME` selects one.

## Version strings and OCI tags

!!! warning
    The `+` character (SemVer build metadata separator) is **not valid in OCI tags**. Write versions with `+` in
    `margo.yaml` — margot automatically converts `+` to `_` when producing OCI tags.

For example:

| `margo.yaml` version | OCI tag pushed |
| ----------------------- | ---------------- |
| `1.0.0+margo` | `1.0.0_margo` |
| `2.1.0+compose-default` | `2.1.0_compose-default` |
| `2.1.0+quadlet-minimal` | `2.1.0_quadlet-minimal` |

This is the standard way to prevent tag collisions when multiple components share the same repository — append
build metadata (`+margo`, `+quadlet`, `+compose-<variant>`, etc.) to distinguish them.

## Template context

When `app.yaml.jinja` is present, margot renders it with Jinja2 using a context derived from `margo.yaml`. The
entire context lives under the `manifest` namespace:

```text
manifest.id  manifest.name  manifest.version  manifest.appVersion  manifest.description
manifest.annotations  manifest.author  manifest.organization

manifest.margo.version  manifest.margo.tag  manifest.margo.ref  manifest.margo.repository  manifest.margo.component

manifest.compose.version  manifest.compose.repository  manifest.compose.component
manifest.compose.variants                          # ordered list of variant objects
manifest.compose.<variant-name>.tag                # direct access by name

manifest.quadlet.*                                 # same shape as compose
```

Each variant object exposes: `name`, `version`, `tag`, `ref`, `repository`, `component`.

- `version` — as authored or derived (with `+`)
- `tag` — OCI-safe form (with `_`). **Computed, not authorable.**
- `ref` — `repository:tag`. **Computed, not authorable.**
- `component` — developer-owned, with a derived default

!!! note
    If `app.yaml.jinja` is absent, `app.yaml` is required and copied verbatim — no substitution occurs.
    Both files present is a hard error.
