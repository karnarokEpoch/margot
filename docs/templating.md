# App description templating

margot supports two forms of the Margo application descriptor inside your `margo/`
directory: a static `app.yaml`, or a Jinja2 template `app.yaml.jinja`. Use one — having
both present at the same time is a hard error.

When `app.yaml.jinja` is present, margot renders it with Jinja2 before every `build`,
`verify`, and `describe` invocation. This lets you derive the entire Margo application
description from the single source of truth you already maintain in `margo.yaml` —
versions, repositories, component names, and OCI references are never duplicated by hand.

## How it works

margot reads `margo.yaml`, builds a context from every field it contains, and passes
that context to Jinja2 as the `manifest` namespace. The rendered output is treated
exactly like a static `app.yaml`.

**Rules:**

- Use `app.yaml.jinja` or `app.yaml` — never both. Both present is a hard error.
- Every variable reference uses `StrictUndefined`: an unresolved variable is a build
  failure, never a silently empty string. Typos are caught immediately.
- `margot build` writes the rendered `app.yaml` to the build output directory (`.dist/`
  by default) alongside the other artifact files. The `app.yaml.jinja` source on disk
  is never modified.
- `margot verify` and `margot describe` render the template to a temporary file and
  discard it after the command completes — nothing is written to `.dist/`.

## Template context reference

The full context available inside `app.yaml.jinja`:

```
manifest
├── id
├── name
├── version
├── appVersion
├── description
├── directory
├── repository
├── annotations                    (dict)
├── author                         (list)
│   └── [n]
│       ├── name
│       └── email
├── organization                   (list)
│   └── [n]
│       ├── name
│       └── site
├── compose                        (dict, present when compose is declared)
│   ├── directory
│   ├── repository
│   ├── version
│   ├── tag                        (computed)
│   ├── ref                        (computed)
│   ├── component                  (flat layout only)
│   ├── variants                   (list)
│   │   └── [n]
│   │       ├── name
│   │       ├── version
│   │       ├── tag                (computed)
│   │       ├── ref                (computed)
│   │       ├── repository
│   │       └── component
│   └── <variant-name>             (direct access, e.g. manifest.compose.default)
│       └── (same fields as variants[n])
└── quadlet                        (dict, present when quadlet is declared)
    └── (same shape as compose)
```

### Top-level fields

All fields live under the `manifest` namespace.

| Variable | Type | Value |
| --- | --- | --- |
| `manifest.id` | string | `id` from `margo.yaml` |
| `manifest.name` | string | `name` from `margo.yaml` |
| `manifest.version` | string | `version` from `margo.yaml` |
| `manifest.appVersion` | string | `appVersion` from `margo.yaml`, or `""` if absent |
| `manifest.description` | string | `description` from `margo.yaml` |
| `manifest.directory` | string | `directory` (margo artifact source dir, default `margo`) |
| `manifest.repository` | string | Top-level `repository`, or `""` if not set |
| `manifest.annotations` | dict | `annotations` key/value pairs, or `{}` if absent |
| `manifest.author` | list | List of `{name, email}` objects |
| `manifest.organization` | list | List of `{name, site}` objects |

### Component fields

`manifest.compose` and `manifest.quadlet` are present when the corresponding component is
declared in `margo.yaml`. Both expose the same shape:

| Variable | Type | Value |
| --- | --- | --- |
| `manifest.<type>.directory` | string | Component source directory |
| `manifest.<type>.repository` | string | Component OCI repository (inherited from top-level if not overridden) |
| `manifest.<type>.version` | string | Component base version (derivation base for variants) |
| `manifest.<type>.tag` | string | `version` with `+` replaced by `_` (OCI-safe) |
| `manifest.<type>.ref` | string | `<repository>:<tag>`, or `""` if either is empty |
| `manifest.<type>.component` | string | Margo component name (flat layout only) |
| `manifest.<type>.variants` | list | Ordered list of variant objects (empty list in flat layout) |
| `manifest.<type>.<name>` | dict | Direct access to a variant by name (e.g. `manifest.compose.default`) |

If a component is not declared in `margo.yaml`, `manifest.compose` / `manifest.quadlet`
resolves to an empty dict `{}`.

### Variant object fields

Each object in `manifest.<type>.variants` (and each `manifest.<type>.<name>`) exposes:

| Field | Type | Derivation |
| --- | --- | --- |
| `name` | string | As declared in `margo.yaml` |
| `version` | string | Authored value, or `<component-version>+<type>-<name>` if omitted |
| `tag` | string | `version` with `+` replaced by `_` — OCI-safe. **Computed, not authorable** |
| `repository` | string | Inherited from component, or overridden per variant |
| `ref` | string | `<repository>:<tag>`. **Computed, not authorable** |
| `component` | string | Authored value, or `<id>-<type>-<name>` if omitted |

!!! note
    `tag` and `ref` are derived fields — they cannot be set in `margo.yaml`. They exist
    purely for use in templates so you never have to compute the OCI-safe tag yourself.

## Basic usage

A minimal `app.yaml.jinja` using only the top-level fields:

```yaml+jinja
apiVersion: v1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: My App
  description: {{ manifest.description }}
  version: {{ manifest.version }}
  catalog:
    organization:
{%- for org in manifest.organization %}
      - name: {{ org.name }}
        site: {{ org.site }}
{%- endfor %}
deploymentProfiles: []
```

Running `margot build` with this `margo.yaml`:

```yaml
apiVersion: v1
id: com-example-myapp
name: myapp
version: "1.0.0"
appVersion: "2.3.1"
description: "My application"
repository: public.ecr.aws/g2n4p2m7/margo
organization:
  - name: Example Corp
    site: https://example.com
```

Produces this `app.yaml` in `.dist/1.0.0/margo/`:

```yaml
apiVersion: v1
kind: ApplicationDescription
id: com-example-myapp
metadata:
  name: My App
  description: My application
  version: 1.0.0
  catalog:
    organization:
      - name: Example Corp
        site: https://example.com
deploymentProfiles: []
```

## Referencing variants in loops

The main power of templating is generating deployment profiles automatically from the
`variants` list. Adding a new variant to `margo.yaml` requires zero edits to `app.yaml.jinja`.

`margo.yaml`:

```yaml
apiVersion: v1
id: com-example-myapp
name: myapp
version: "1.0.0"
appVersion: "2.3.1"
description: "My application"
repository: public.ecr.aws/g2n4p2m7/margo
organization:
  - name: Example Corp
    site: https://example.com

compose:
  version: 1.0.0
  variants:
    - name: default
    - name: minimal
```

`margo/app.yaml.jinja`:

```yaml+jinja
apiVersion: v1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: My App
  description: {{ manifest.description }}
  version: {{ manifest.version }}
  catalog:
    organization:
{%- for org in manifest.organization %}
      - name: {{ org.name }}
        site: {{ org.site }}
{%- endfor %}

deploymentProfiles:
{%- for v in manifest.compose.variants %}
  - type: compose
    id: {{ manifest.id }}-compose-{{ v.name }}
    components:
      - name: {{ v.component }}
        properties:
          repository: oci://{{ v.repository }}
          revision: {{ v.tag }}
{%- endfor %}
```

Rendered output:

```yaml
apiVersion: v1
kind: ApplicationDescription
id: com-example-myapp
metadata:
  name: My App
  description: My application
  version: 1.0.0
  catalog:
    organization:
      - name: Example Corp
        site: https://example.com

deploymentProfiles:
  - type: compose
    id: com-example-myapp-compose-default
    components:
      - name: com-example-myapp-compose-default
        properties:
          repository: oci://public.ecr.aws/g2n4p2m7/margo
          revision: 1.0.0_compose-default
  - type: compose
    id: com-example-myapp-compose-minimal
    components:
      - name: com-example-myapp-compose-minimal
        properties:
          repository: oci://public.ecr.aws/g2n4p2m7/margo
          revision: 1.0.0_compose-minimal
```

Notice that `oci://` is prepended inside the template — the `v.repository` value contains
the bare registry/repository path (`public.ecr.aws/g2n4p2m7/margo`) without any scheme.
The Margo spec requires the `oci://` prefix in `properties.repository`, so it belongs in
the template.

## Accessing a variant by name

When you need to reference a specific variant (for example, to pin a known revision in a
second profile), access it by name directly instead of iterating:

```yaml+jinja
deploymentProfiles:
  - type: compose
    id: {{ manifest.id }}-compose-production
    components:
      - name: {{ manifest.compose.default.component }}
        properties:
          repository: oci://{{ manifest.compose.default.repository }}
          revision: {{ manifest.compose.default.tag }}
```

This is equivalent to the loop result for the `default` variant, but explicit.

## Iterating over both compose and quadlet variants

When a project ships both component types, combine both variant lists:

```yaml+jinja
parameters:
  nginxPort:
    value: 8080
    targets:
      - pointer: NGINX_PORT
        components:
{%- for v in manifest.compose.variants + manifest.quadlet.variants %}
          - {{ v.component }}
{%- endfor %}
```

`manifest.compose.variants + manifest.quadlet.variants` is standard Jinja2 list
concatenation — no custom filter needed.

## Using appVersion

`appVersion` tracks the version of the deployed application (like Helm's `appVersion`).
A common pattern is to pass it as the image tag for a Helm component:

```yaml+jinja
deploymentProfiles:
  - type: helm
    id: {{ manifest.id }}-helm
    components:
      - name: nginx
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/nginx
          revision: 18.1.7

parameters:
  nginxImageTag:
    value: "{{ manifest.appVersion }}"
    targets:
      - pointer: image.tag
        components:
          - nginx
```

Bumping `appVersion` in `margo.yaml` propagates to every parameter that references
`manifest.appVersion` — no other edits required.

## Looping over catalog fields

`manifest.author` and `manifest.organization` are lists you can iterate over:

```yaml+jinja
metadata:
  catalog:
    organization:
{%- for org in manifest.organization %}
      - name: {{ org.name }}
        site: {{ org.site }}
{%- endfor %}
    author:
{%- for a in manifest.author %}
      - name: {{ a.name }}
        email: {{ a.email }}
{%- endfor %}
```

## Conditional blocks

Use Jinja2 `if` to include a section only when a component is declared:

```yaml+jinja
deploymentProfiles:
{%- if manifest.compose %}
{%- for v in manifest.compose.variants %}
  - type: compose
    id: {{ manifest.id }}-compose-{{ v.name }}
    components:
      - name: {{ v.component }}
        properties:
          repository: oci://{{ v.repository }}
          revision: {{ v.tag }}
{%- endfor %}
{%- endif %}
{%- if manifest.quadlet %}
{%- for v in manifest.quadlet.variants %}
  - type: quadlet
    id: {{ manifest.id }}-quadlet-{{ v.name }}
    components:
      - name: {{ v.component }}
        properties:
          repository: oci://{{ v.repository }}
          revision: {{ v.tag }}
{%- endfor %}
{%- endif %}
```

This is useful for shared template stubs that work regardless of which components are
declared in a given project.

## Annotations

`manifest.annotations` is a plain dict. Iterate over it with `.items()`:

```yaml+jinja
metadata:
  extensions:
{%- for key, value in manifest.annotations.items() %}
    {{ key }}: "{{ value }}"
{%- endfor %}
```

## Error behavior

| Situation | Behavior |
| --- | --- |
| Undefined variable (e.g. typo in `{{ manifest.vesion }}`) | Hard error at build/verify/describe time. Never silent. |
| Both `app.yaml` and `app.yaml.jinja` present | Hard error. |
| Only `app.yaml` present | Copied verbatim — no rendering. |
| `app.yaml.jinja` absent and `app.yaml` absent | Hard error. |

## See also

- [margo.yaml reference](margo-yaml.md) — all `margo.yaml` fields and their semantics.
- [Image search-and-replace](examples/image-search-replace.md) — the `image.replace` field in `compose` and `quadlet` components also uses the same template context.
- [Full example](examples/full.md) — a complete multi-component project with variants, Helm, compose, and quadlet in a single `app.yaml.jinja`.
