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
directory: margo
repository: public.ecr.aws/g2n4p2m7/margo
annotations:
  opentelemetry.io/instrumented: "true"
author:
  - name: Alice Example
    email: alice@example.com
organization:
  - name: Example Corp
    site: https://example.com

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
| `directory` | No | Path to the margo artifact source directory. Default: `margo`. |
| `repository` | No | Default OCI repository for all artifacts. Overridable per component. Can also be set via tool config / CLI / env. |

## Components

`compose` and `quadlet` declare deployment components — each producing a separate OCI artifact when built.

### compose

A Docker Compose deployment artifact. Can be built as a single artifact (flat layout) or as multiple variant
artifacts.

### quadlet

A systemd Quadlet deployment artifact. Same structure and variant support as `compose`.

### compose / quadlet fields

| Field | Required | Default | Description |
| ------- | ---------- | --------- | ------------- |
| `version` | Yes | — | Base version for the component. Used directly as OCI tag in flat mode; used as the derivation base for variant versions. |
| `repository` | No | Global `repository` from tool config / CLI / env | OCI repository for this component. |
| `component` | No | `<id>-<type>` | Margo component name (developer-owned). Flat mode only. |
| `directory` | No | `<type>` (i.e. `compose` or `quadlet`) | Path (relative to project root) to the component source directory. |
| `image` | No | — | `{search, replace}` block — swaps a dev-local image reference for the target one at build time. See [Image search-and-replace](#image-search-and-replace). Not available for `margo`. |

## Image search-and-replace

`compose` and `quadlet` sources are meant to be **runnable as checked in** — a developer runs
`compose/compose.yaml` or `quadlet/*.container` locally against a dev-local image (e.g. built with
`podman build -t localhost/myapp:dev .`) before margot ever touches it. At build time, margot swaps that
dev-local reference for the environment-appropriate one — no manual editing of source files, no
drift between what's run locally and what's shipped.

```yaml
compose:
  directory: compose
  version: 1.0.0
  image:
    search: "localhost/myapp:dev"
    replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}"
```

- `search` — a **literal string** (not a regex), exactly as it appears in the component's source
  text file(s), e.g. `localhost/myapp:dev`.
- `replace` — a **Jinja2 template string**, rendered with the same [template context](#template-context)
  used for `app.yaml.jinja`. Rendered once at build time, after every other `margo.yaml` field is
  resolved — so bumping `appVersion` (or any other manifest field) alone updates every
  `image.replace` result, with no separate edit to the `image` block itself.
- May be declared at the component level (`compose:` / `quadlet:`) and/or per variant. A variant's
  `image` block **fully overrides** the component-level one — it does not merge.
- Optional. A component/variant with no `image` block gets no substitution.
- An unmatched `search` string (declared but not found in any source file) produces a warning, not
  a hard failure — the same posture as other unresolved placeholders.
- An undefined Jinja variable in `replace` is a hard error at build time (fail fast), not a silent
  empty string — same behavior as an invalid `app.yaml.jinja` template.
- Not available for `margo` — `margo/app.yaml` (or `app.yaml.jinja`) is only ever rendered once at
  build time and is never run directly, so it uses `app.yaml.jinja` directly instead.

Per-variant override:

```yaml
compose:
  directory: compose
  version: 1.0.0
  image:
    search: "localhost/myapp:dev"
    replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}"
  variants:
    - name: default        # inherits the component-level image block above
    - name: addon-mosquitto
      image:                # fully replaces the component-level block for this variant
        search: "localhost/mosquitto:dev"
        replace: "public.ecr.aws/g2n4p2m7/mosquitto:{{ manifest.appVersion }}"
```

See the [Image search-and-replace example](examples/image-search-replace.md) for a full walkthrough
with `margot build` output.

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

| Field | Required | Default | Description |
| ------- | ---------- | --------- | ------------- |
| `name` | Yes | — | Variant name. Maps to `<directory>/<name>/` subdirectory. |
| `version` | No | `<component-version>+<type>-<variant-name>` | OCI version for this variant. |
| `component` | No | `<id>-<type>-<variant-name>` | Margo component name for this variant. |

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
| `1.0.0+quadlet` | `1.0.0_quadlet` |
| `2.1.0+compose-default` | `2.1.0_compose-default` |
| `2.1.0+quadlet-minimal` | `2.1.0_quadlet-minimal` |

This is the standard way to prevent tag collisions when multiple components share the same repository — append
build metadata (`+margo`, `+quadlet`, `+compose-<variant>`, etc.) to distinguish them.

## Template context

When `app.yaml.jinja` is present, margot renders it with Jinja2 using a context derived from `margo.yaml`. The
entire context lives under the `manifest` namespace:

- `manifest`
  - `id`, `name`, `version`, `appVersion`, `description`
  - `directory`, `repository`
  - `annotations` — dict
  - `author` — list of `{name, email}`
  - `organization` — list of `{name, site}`
  - `compose` and `quadlet`
    - `version`, `repository`, `component`
    - `variants` — ordered list of variant objects
    - `<variant-name>` — direct access (e.g. `manifest.compose.default.tag`)

Each **variant object** exposes:

| Field | Derivation |
| ------- | ------------ |
| `name` | As declared in `margo.yaml`. |
| `version` | Authored value, or `<component-version>+<type>-<name>` if omitted. |
| `tag` | `version` with `+` replaced by `_`. **Computed, not authorable.** |
| `ref` | `<repository>:<tag>`. **Computed, not authorable.** |
| `repository` | Inherited from component, or overridden per variant. |
| `component` | Authored value, or `<id>-<type>-<name>` if omitted. |

!!! note
    If `app.yaml.jinja` is absent, `app.yaml` is required and copied verbatim — no substitution occurs.
    Both files present is a hard error.
