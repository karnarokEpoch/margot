# Full — Multi-component with variants

A project packaging **nginx + apache** with both `quadlet` and `compose` deployment components, multiple variants,
and symlinks to avoid file duplication. This is the most realistic production layout.

## Project tree

```
web-platform/
├── margo.yaml
├── margo/
│   ├── app.yaml.jinja
│   └── resources/
│       ├── icon.png
│       └── description.md
├── compose/
│   ├── default/
│   │   ├── compose.yaml
│   │   └── .env
│   └── minimal/
│       ├── compose.yaml
│       └── .env
└── quadlet/
    ├── default/
    │   ├── nginx.container
    │   ├── apache.container
    │   ├── web.network
    │   ├── nginx-index.html
    │   └── apache-index.html
    └── minimal/
        ├── nginx.container
        ├── web.network -> ../default/web.network
        └── nginx-index.html -> ../default/nginx-index.html
```

The `minimal` quadlet variant uses **symlinks** for shared files (`web.network`, `nginx-index.html`). margot's builder
resolves symlinks and copies their content — the pushed artifact contains regular files.

## margo.yaml

```yaml
apiVersion: v1
id: com-example-web-platform
name: web-platform
version: "1.0.0"
appVersion: "2.1.0"
description: "NGINX + Apache web platform"
repository: public.ecr.aws/g2n4p2m7/margo
annotations:
  team: platform-engineering
author:
  - name: Alice Example
    email: alice@example.com
organization:
  - name: Example Corp
    site: https://example.com

compose:
  version: 2.1.0
  variants:
    - name: default
    - name: minimal

quadlet:
  version: 2.1.0
  variants:
    - name: default
    - name: minimal
```

Variant `version` is omitted — margot derives it as `<component-version>+<type>-<variant-name>`:

| Variant | Derived version | OCI tag |
| --------- | ----------------- | --------- |
| compose/default | `2.1.0+compose-default` | `2.1.0_compose-default` |
| compose/minimal | `2.1.0+compose-minimal` | `2.1.0_compose-minimal` |
| quadlet/default | `2.1.0+quadlet-default` | `2.1.0_quadlet-default` |
| quadlet/minimal | `2.1.0+quadlet-minimal` | `2.1.0_quadlet-minimal` |

No tag collisions, no manual versioning per variant.

## app.yaml.jinja

```yaml+jinja
apiVersion: margo.org/v1-alpha1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: Web Platform
  description: {{ manifest.description }}
  version: {{ manifest.version }}
  catalog:
    application:
      icon: ./resources/icon.png
      descriptionFile: ./resources/description.md
      tags: ["web", "reverse-proxy"]
    organization:
{%- for org in manifest.organization %}
      - name: {{ org.name }}
        site: {{ org.site }}
{%- endfor %}

deploymentProfiles:
  - type: helm
    id: {{ manifest.id }}-helm
    components:
      - name: nginx
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/nginx
          revision: 25.0.15
      - name: apache
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/apache
          revision: 11.4.29
{%- for v in manifest.compose.variants %}
  - type: compose
    id: {{ manifest.id }}-compose-{{ v.name }}
    components:
      - name: {{ v.component }}
        properties:
          repository: oci://{{ v.repository }}
          revision: {{ v.tag }}
{%- endfor %}
{%- for v in manifest.quadlet.variants %}
  - type: quadlet
    id: {{ manifest.id }}-quadlet-{{ v.name }}
    components:
      - name: {{ v.component }}
        properties:
          repository: oci://{{ v.repository }}
          revision: {{ v.tag }}
{%- endfor %}

parameters:
  nginxPort:
    value: 8080
    targets:
      - pointer: NGINX_PORT
        components:
{%- for v in manifest.compose.variants + manifest.quadlet.variants %}
          - {{ v.component }}
{%- endfor %}

configuration:
  sections:
    - name: Networking
      settings:
        - parameter: nginxPort
          name: NGINX Port
          description: Host port the NGINX component listens on.
          schema: portSchema
  schema:
    - name: portSchema
      dataType: integer
      minValue: 1
      maxValue: 65535
      allowEmpty: false
```

Adding a new variant to `margo.yaml` requires **zero edits** to `app.yaml.jinja` — the loops pick it up
automatically. At build time, the context resolves to:

- `{{ v.component }}` → `com-example-web-platform-compose-default`, etc. (derived: `<id>-<type>-<variant-name>`)
- `{{ v.tag }}` → `2.1.0_compose-default`, etc. (OCI-safe form of the derived version)
- `{{ v.repository }}` → `public.ecr.aws/g2n4p2m7/margo` (bare registry/repository — the `oci://`
  scheme required by `deploymentProfiles[].components[].properties.repository` is prepended in
  the template, not part of the context value)

## Inspect with describe

`margot describe` renders the application descriptor as structured panels and trees — read-only inspection of the
descriptor, no schema validation, no network, no prior build required. This is the natural thing to run before
`build` and `push` to sanity-check the descriptor.

```bash
margot describe
```

This produces three output panels: identity metadata (name, version, OCI URI, catalog), deployment profiles (tree of
types, components, and their properties), and configuration (settings, parameters, and schemas).

```
╭──────────────────────────── margo.org/v1-alpha1 ─────────────────────────────╮
│ id    com-example-web-platform  version  1.0.0                               │
│ name  Web Platform                                                           │
│                                                                              │
│ OCI: public.ecr.aws/g2n4p2m7/margo:1.0.0                                     │
│ Description: NGINX + Apache web platform                                     │
│ Catalog:                                                                     │
│     tagline             —                                                    │
│     site                —                                                    │
│     icon                ./resources/icon.png                                 │
│     descriptionFile     ./resources/description.md                           │
│     licenseFile         —                                                    │
│     releaseNotes        —                                                    │
│     tags                web · reverse-proxy                                  │
│     author              —                                                    │
│     organization        Example Corp — https://example.com                   │
╰────────────────────── margo/app.yaml.jinja (rendered) ───────────────────────╯
╭────────────── Deployment profiles (5 profiles · 6 components) ───────────────╮
│ helm  com-example-web-platform-helm                                          │
│ └── components                                                               │
│     ├── nginx                                                                │
│     │   ├── repository  oci://registry-1.docker.io/bitnamicharts/nginx       │
│     │   └── revision    25.0.15                                              │
│     └── apache                                                               │
│         ├── repository  oci://registry-1.docker.io/bitnamicharts/apache      │
│         └── revision    11.4.29                                              │
│                                                                              │
│ compose  com-example-web-platform-compose-default                            │
│ └── components                                                               │
│     └── com-example-web-platform-compose-default                             │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/margo                  │
│         └── revision    2.1.0_compose-default                                │
│                                                                              │
│ compose  com-example-web-platform-compose-minimal                            │
│ └── components                                                               │
│     └── com-example-web-platform-compose-minimal                             │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/margo                  │
│         └── revision    2.1.0_compose-minimal                                │
│                                                                              │
│ quadlet  com-example-web-platform-quadlet-default                            │
│ └── components                                                               │
│     └── com-example-web-platform-quadlet-default                             │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/margo                  │
│         └── revision    2.1.0_quadlet-default                                │
│                                                                              │
│ quadlet  com-example-web-platform-quadlet-minimal                            │
│ └── components                                                               │
│     └── com-example-web-platform-quadlet-minimal                             │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/margo                  │
│         └── revision    2.1.0_quadlet-minimal                                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭────────────────── Configuration (1 sections · 1 settings) ───────────────────╮
│ Networking  [Section]                                                        │
│ └── NGINX Port  [Setting]                                                    │
│     ├── Schema: portSchema  integer  1..65535 · allowEmpty false             │
│     └── Parameter: nginxPort  8080                                           │
│         └── Pointer: "NGINX_PORT"  (4/6 components)                          │
│             ├── com-example-web-platform-compose-default                     │
│             ├── com-example-web-platform-compose-minimal                     │
│             ├── com-example-web-platform-quadlet-default                     │
│             └── com-example-web-platform-quadlet-minimal                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

The configuration now includes the `nginxPort` setting properly wired to its schema and all component targets.

### Component-first view

Use `--section component-first` to see an alternative view listing each component with its incoming parameters.
This is useful when understanding what configuration a specific component needs.

```
╭───────────────────────── Components (6 components) ──────────────────────────╮
│ nginx  [Component]                                                           │
│ └── no parameters                                                            │
│                                                                              │
│ apache  [Component]                                                          │
│ └── no parameters                                                            │
│                                                                              │
│ com-example-web-platform-compose-default  [Component]                        │
│ └── nginxPort  "NGINX_PORT"  [Parameter]                                     │
│     ├── Value: 8080                                                          │
│     ├── Setting: NGINX Port                                                  │
│     └── Schema: portSchema  integer  1..65535 · allowEmpty false             │
│                                                                              │
│ com-example-web-platform-compose-minimal  [Component]                        │
│ └── nginxPort  "NGINX_PORT"  [Parameter]                                     │
│     ├── Value: 8080                                                          │
│     ├── Setting: NGINX Port                                                  │
│     └── Schema: portSchema  integer  1..65535 · allowEmpty false             │
│                                                                              │
│ com-example-web-platform-quadlet-default  [Component]                        │
│ └── nginxPort  "NGINX_PORT"  [Parameter]                                     │
│     ├── Value: 8080                                                          │
│     ├── Setting: NGINX Port                                                  │
│     └── Schema: portSchema  integer  1..65535 · allowEmpty false             │
│                                                                              │
│ com-example-web-platform-quadlet-minimal  [Component]                        │
│ └── nginxPort  "NGINX_PORT"  [Parameter]                                     │
│     ├── Value: 8080                                                          │
│     ├── Setting: NGINX Port                                                  │
│     └── Schema: portSchema  integer  1..65535 · allowEmpty false             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

The compose and quadlet components now show their incoming `nginxPort` parameter with its schema details.

## Compose files

### default

#### compose.yaml

```yaml
services:
  nginx:
    image: docker.io/library/nginx:1.27.0
    ports:
      - "${NGINX_PORT:-8080}:80"
    networks:
      - web

  apache:
    image: docker.io/library/httpd:2.4
    ports:
      - "8081:80"
    networks:
      - web

networks:
  web:
    driver: bridge
```

### minimal

#### compose.yaml

```yaml
services:
  nginx:
    image: docker.io/library/nginx:1.27.0
    ports:
      - "${NGINX_PORT:-8080}:80"
```

The minimal variant ships only nginx, no apache.

## Quadlet files

Note: `${NGINX_PORT}` in the quadlet `PublishPort=` is resolved by the deploying Margo device at deploy time (not by margot during build), and the `Environment=NGINX_PORT=8080` in the `[Service]` section supplies the default value if not overridden by the device.

### default

#### nginx.container

```ini
[Container]
Image=docker.io/library/nginx:1.27.0
PublishPort=${NGINX_PORT}:80
Network=web.network
Volume=%h/.config/containers/systemd/nginx-index.html:/usr/share/nginx/html/index.html:ro

[Service]
Environment=NGINX_PORT=8080

[Install]
WantedBy=default.target
```

#### apache.container

```ini
[Container]
Image=docker.io/library/httpd:2.4
PublishPort=8081:80
Network=web.network
Volume=%h/.config/containers/systemd/apache-index.html:/usr/local/apache2/htdocs/index.html:ro

[Install]
WantedBy=default.target
```

#### web.network

```ini
[Network]
Subnet=10.89.1.0/24
Gateway=10.89.1.1
```

#### nginx-index.html

```html
<!DOCTYPE html>
<html>
<head><title>NGINX</title></head>
<body><h1>Hello from NGINX</h1></body>
</html>
```

#### apache-index.html

```html
<!DOCTYPE html>
<html>
<head><title>Apache</title></head>
<body><h1>Hello from Apache</h1></body>
</html>
```

### minimal

#### nginx.container

```ini
[Container]
Image=docker.io/library/nginx:1.27.0
PublishPort=${NGINX_PORT}:80
Network=web.network
Volume=%h/.config/containers/systemd/nginx-index.html:/usr/share/nginx/html/index.html:ro

[Service]
Environment=NGINX_PORT=8080

[Install]
WantedBy=default.target
```

#### web.network

```ini
[Network]
Subnet=10.89.1.0/24
Gateway=10.89.1.1
```

#### nginx-index.html

```html
<!DOCTYPE html>
<html>
<head><title>NGINX</title></head>
<body><h1>Hello from NGINX</h1></body>
</html>
```

The `web.network` and `nginx-index.html` in `quadlet/minimal/` are symlinks to their counterparts in
`quadlet/default/`. No file duplication needed — margot resolves symlinks at build time and copies the actual content.

## Build and push

```bash
# Build everything (all components, all variants)
margot build

# Or build selectively
margot build --type quadlet --variant minimal

# Push all
margot push
```

This produces five OCI artifacts at `public.ecr.aws/g2n4p2m7/margo`:

| Tag | Artifact type |
| ----- | --------------- |
| `1.0.0` | `application/vnd.margo.app.v1+json` |
| `2.1.0_compose-default` | `application/vnd.org.margo.component.compose+json` |
| `2.1.0_compose-minimal` | `application/vnd.org.margo.component.compose+json` |
| `2.1.0_quadlet-default` | `application/vnd.org.margo.component.quadlet+json` |
| `2.1.0_quadlet-minimal` | `application/vnd.org.margo.component.quadlet+json` |
