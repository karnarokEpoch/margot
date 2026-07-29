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
appVersion: "2.1.0"
description: "NGINX + Apache web platform"
annotations:
  team: platform-engineering
maintainers:
  - name: Alice Example
    email: alice@example.com

margo:
  directory: margo
  version: 1.0.0+margo
  repository: public.ecr.aws/g2n4p2m7/margo

compose:
  directory: compose
  version: 2.1.0
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default
    - name: minimal

quadlet:
  directory: quadlet
  version: 2.1.0
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default
    - name: minimal
```

Variant `version` is omitted — margot derives it as `<component-version>+<type>-<variant-name>`:

| Variant | Derived version | OCI tag |
|---------|-----------------|---------|
| compose/default | `2.1.0+compose-default` | `2.1.0_compose-default` |
| compose/minimal | `2.1.0+compose-minimal` | `2.1.0_compose-minimal` |
| quadlet/default | `2.1.0+quadlet-default` | `2.1.0_quadlet-default` |
| quadlet/minimal | `2.1.0+quadlet-minimal` | `2.1.0_quadlet-minimal` |

No tag collisions, no manual versioning per variant.

## app.yaml.jinja

```jinja
apiVersion: margo.org/v1-alpha1
kind: ApplicationDescription
id: {{ app.id }}
metadata:
  name: Web Platform
  description: {{ app.description }}
  version: {{ app.version }}
  catalog:
    application:
      icon: ./resources/icon.png
      descriptionFile: ./resources/description.md
      tags: ["web", "reverse-proxy"]
    organization:
      - name: Example Corp
        site: https://example.com

deploymentProfiles:
  - type: helm
    id: {{ app.id }}-helm
    components:
      - name: nginx
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/nginx
          revision: 25.0.15
      - name: apache
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/apache
          revision: 11.4.29
{%- for v in compose.variants %}
  - type: compose
    id: {{ app.id }}-compose-{{ v.name }}
    components:
      - name: {{ v.component }}
        properties:
          repository: {{ v.repository }}
          revision: {{ v.tag }}
{%- endfor %}
{%- for v in quadlet.variants %}
  - type: quadlet
    id: {{ app.id }}-quadlet-{{ v.name }}
    components:
      - name: {{ v.component }}
        properties:
          repository: {{ v.repository }}
          revision: {{ v.tag }}
{%- endfor %}

parameters:
  nginxPort:
    value: 8080
    targets:
      - pointer: NGINX_PORT
        components:
{%- for v in compose.variants + quadlet.variants %}
          - {{ v.component }}
{%- endfor %}
```

Adding a new variant to `margo.yaml` requires **zero edits** to `app.yaml.jinja` — the loops pick it up
automatically. At build time, the context resolves to:

- `{{ v.component }}` → `com-example-web-platform-compose-default`, etc. (derived: `<id>-<type>-<variant-name>`)
- `{{ v.tag }}` → `2.1.0_compose-default`, etc. (OCI-safe form of the derived version)
- `{{ v.repository }}` → `public.ecr.aws/g2n4p2m7/margo`

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

### default

#### nginx.container

```ini
[Container]
Image=docker.io/library/nginx:1.27.0
PublishPort=8080:80
Network=web.network
Volume=%h/.config/containers/systemd/nginx-index.html:/usr/share/nginx/html/index.html:ro

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
PublishPort=8080:80
Network=web.network
Volume=%h/.config/containers/systemd/nginx-index.html:/usr/share/nginx/html/index.html:ro

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
|-----|---------------|
| `1.0.0_margo` | `application/vnd.margo.app.v1+json` |
| `2.1.0_compose-default` | `application/vnd.org.margo.component.compose+json` |
| `2.1.0_compose-minimal` | `application/vnd.org.margo.component.compose+json` |
| `2.1.0_quadlet-default` | `application/vnd.org.margo.component.quadlet+json` |
| `2.1.0_quadlet-minimal` | `application/vnd.org.margo.component.quadlet+json` |
