# Full — Multi-component with variants

A project packaging **nginx + apache** with both `quadlet` and `compose` deployment components, multiple variants,
and symlinks to avoid file duplication. This is the most realistic production layout.

## Project tree

```
web-platform/
├── margo.yaml
├── margo/
│   ├── app.yaml
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
        ├── nginx.container -> ../default/nginx.container
        ├── web.network -> ../default/web.network
        └── nginx-index.html -> ../default/nginx-index.html
```

The `minimal` quadlet variant uses **symlinks** for shared files (`nginx.container`, `web.network`, `nginx-index.html`).
margot's builder resolves symlinks and copies their content — the pushed artifact contains regular files.

## margo.yaml

```yaml
apiVersion: v1
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
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default
      version: 2.1.0+compose
    - name: minimal
      version: 2.1.0+compose-minimal

quadlet:
  directory: quadlet
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default
      version: 2.1.0+quadlet
    - name: minimal
      version: 2.1.0+quadlet-minimal
```

Each component has two variants. The build metadata suffix (`+compose`, `+quadlet`, `+compose-minimal`, etc.) prevents
tag collisions since all artifacts share the same repository. Remember: `+` is converted to `_` in OCI tags.

## app.yaml

```yaml
apiVersion: margo.org/v1-alpha1
kind: ApplicationDescription
id: com-example-web-platform
metadata:
  name: Web Platform
  description: NGINX + Apache web platform
  version: <app_tag>
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
    id: com-example-web-platform-helm
    components:
      - name: nginx
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/nginx
          revision: 25.0.15
      - name: apache
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/apache
          revision: 11.4.29
  - type: compose
    id: com-example-web-platform-compose-default
    components:
      - name: web-platform-compose-default
        properties:
          repository: public.ecr.aws/g2n4p2m7/margo
          revision: <compose_tag>
  - type: compose
    id: com-example-web-platform-compose-minimal
    components:
      - name: web-platform-compose-minimal
        properties:
          repository: public.ecr.aws/g2n4p2m7/margo
          revision: 2.1.0_compose-minimal
  - type: quadlet
    id: com-example-web-platform-quadlet-default
    components:
      - name: web-platform-quadlet-default
        properties:
          repository: public.ecr.aws/g2n4p2m7/margo
          revision: <quadlet_tag>
  - type: quadlet
    id: com-example-web-platform-quadlet-minimal
    components:
      - name: web-platform-quadlet-minimal
        properties:
          repository: public.ecr.aws/g2n4p2m7/margo
          revision: 2.1.0_quadlet-minimal
parameters:
  nginxPort:
    value: 8080
    targets:
      - pointer: NGINX_PORT
        components:
          - web-platform-compose-default
          - web-platform-compose-minimal
          - web-platform-quadlet-default
          - web-platform-quadlet-minimal
```

`<app_tag>` → `2.1.0`, `<compose_tag>` → `2.1.0_compose` (first compose variant), `<quadlet_tag>` → `2.1.0_quadlet`
(first quadlet variant).

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
| ----- | --------------- |
| `1.0.0_margo` | `application/vnd.margo.app.v1+json` |
| `2.1.0_compose` | `application/vnd.org.margo.component.compose+json` |
| `2.1.0_compose-minimal` | `application/vnd.org.margo.component.compose+json` |
| `2.1.0_quadlet` | `application/vnd.org.margo.component.quadlet+json` |
| `2.1.0_quadlet-minimal` | `application/vnd.org.margo.component.quadlet+json` |
