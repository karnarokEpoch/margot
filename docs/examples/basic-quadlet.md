# Basic — Quadlet deployment

An nginx application with a `margo` component (application descriptor) and a single `quadlet` deployment component.
No variants — flat layout.

## Project tree

```
nginx-quadlet/
├── margo.yaml
├── margo/
│   └── app.yaml.jinja
└── quadlet/
    └── nginx.container
```

## margo.yaml

```yaml
apiVersion: v1
id: com-example-nginx
name: nginx
version: "1.0.0"
appVersion: "1.27.0"
description: "NGINX web server deployed via Quadlet"

margo:
  directory: margo
  version: 1.0.0+margo
  repository: public.ecr.aws/g2n4p2m7/margo

quadlet:
  directory: quadlet
  version: 1.0.0+quadlet
  repository: public.ecr.aws/g2n4p2m7/margo
```

No `variants` — the `quadlet/` directory is built as a single artifact. The `+margo` and `+quadlet` build metadata
suffixes prevent tag collision when both artifacts share the same repository.

!!! warning
    The `+` character is not valid in OCI tags. margot automatically converts `+` to `_` when pushing, so
    `1.0.0+margo` becomes OCI tag `1.0.0_margo`. Write versions with `+` in `margo.yaml` — the conversion is
    handled transparently.

## app.yaml.jinja

```yaml+jinja
apiVersion: margo.org/v1-alpha1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: NGINX
  description: {{ manifest.description }}
  version: {{ manifest.version }}
deploymentProfiles:
  - type: quadlet
    id: {{ manifest.id }}-quadlet
    components:
      - name: {{ manifest.quadlet.component }}
        properties:
          repository: {{ manifest.quadlet.repository }}
          revision: {{ manifest.quadlet.tag }}
```

At build time:

- `{{ manifest.id }}` → `com-example-nginx`
- `{{ manifest.version }}` → `1.0.0` (manifest version)
- `{{ manifest.quadlet.component }}` → `com-example-nginx-quadlet` (derived: `<id>-<type>`)
- `{{ manifest.quadlet.tag }}` → `1.0.0_quadlet` (OCI-safe form of `1.0.0+quadlet`)

## Quadlet files

### nginx.container

```ini
[Container]
Image=docker.io/library/nginx:1.27.0
PublishPort=8080:80

[Install]
WantedBy=default.target
```

## Build and push

```bash
margot build
margot push
```

This produces two OCI artifacts at `public.ecr.aws/g2n4p2m7/margo`:

| Tag | Artifact type |
|-----|---------------|
| `1.0.0_margo` | `application/vnd.margo.app.v1+json` |
| `1.0.0_quadlet` | `application/vnd.org.margo.component.quadlet+json` |
