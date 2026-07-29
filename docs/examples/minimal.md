# Minimal — Helm deployment profile

The simplest margot project: a single `margo` component that describes an nginx application deployed via an
**existing** Helm chart. margot packages and pushes the application descriptor — it does not build the Helm chart
itself.

## Project tree

```
nginx-helm/
├── margo.yaml
└── margo/
    └── app.yaml
```

## margo.yaml

```yaml
apiVersion: v1
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

## app.yaml

The Margo application description references a Helm chart already published in an OCI registry:

```yaml
apiVersion: margo.org/v1-alpha1
kind: ApplicationDescription
id: com-example-nginx
metadata:
  name: NGINX
  description: NGINX web server
  version: <app_tag>
deploymentProfiles:
  - type: helm
    id: com-example-nginx-helm
    components:
      - name: nginx
        properties:
          repository: oci://registry-1.docker.io/bitnamicharts/nginx
          revision: 25.0.15
          wait: true
          timeout: 5m0s
```

The `<app_tag>` placeholder is substituted at build time with the `appVersion` value from `margo.yaml` (`1.27.0`).

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
