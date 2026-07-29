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
appVersion: "1.27.0"
description: "NGINX web server deployed via Helm chart"

margo:
  directory: margo
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
```

Only the `margo` component is declared — no `compose`, no `quadlet`. margot builds and pushes the application
descriptor artifact only.

## app.yaml.jinja

```jinja
apiVersion: margo.org/v1-alpha1
kind: ApplicationDescription
id: {{ app.id }}
metadata:
  name: NGINX
  description: {{ app.description }}
  version: {{ app.version }}
deploymentProfiles:
  - type: helm
    id: {{ app.id }}-helm
    components:
      - name: nginx
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/nginx
          revision: 25.0.15
          wait: true
          timeout: 5m0s
```

`{{ app.version }}` resolves to `1.27.0` (from `appVersion`), `{{ app.id }}` to `com-example-nginx`.

!!! note
    `parameters` and `configuration` sections are omitted here to keep the example short. In a real project you
    would define configurable values (e.g. replica count, resource limits) and their validation schema. See the
    [full example](full.md) for a project with parameters.

## Build and push

```bash
margot build
margot push
```

This pushes a single OCI artifact to `public.ecr.aws/g2n4p2m7/margo:1.0.0` with artifact type
`application/vnd.margo.app.v1+json`.
