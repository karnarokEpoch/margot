# Minimal — Helm deployment profile

The simplest margot project: a single `margo` component that describes an nginx application deployed via an
**existing** Helm chart. margot packages and pushes the application descriptor — it does not build the Helm chart
itself.

## Project tree

```
nginx-helm/
├── margo.yaml
└── margo/
    └── app.yaml.jinja
```

## margo.yaml

```yaml
apiVersion: v1
id: com-example-nginx
name: nginx
version: "1.0.0"
appVersion: "1.27.0"
description: "NGINX web server deployed via Helm chart"

margo:
  directory: margo
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
```

- `version` — the manifest/package version (this Margo application description release)
- `appVersion` — the version of the deployed application (nginx `1.27.0`)

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
  - type: helm
    id: {{ manifest.id }}-helm
    components:
      - name: nginx
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/nginx
          revision: 25.0.15
          wait: true
          timeout: 5m0s
parameters:
  imageTag:
    value: {{ manifest.appVersion }}
    targets:
      - pointer: image.tag
        components: ["nginx"]
```

- `{{ manifest.version }}` → `1.0.0` (manifest version)
- `{{ manifest.appVersion }}` → `1.27.0` (application version, used as the default for `image.tag`)

## Build and push

```bash
margot build
margot push
```

This pushes a single OCI artifact to `public.ecr.aws/g2n4p2m7/margo:1.0.0` with artifact type
`application/vnd.margo.app.v1+json`.
