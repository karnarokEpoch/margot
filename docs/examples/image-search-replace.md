# Image search-and-replace — Compose

A `compose` component whose `compose.yaml` is runnable locally as-is against a dev-local image.
`margot build` swaps that dev-local reference for the target registry image — no manual editing,
no drift between what you run locally and what gets pushed.

## Project tree

```
myapp-compose/
├── margo.yaml
├── margo/
│   └── app.yaml.jinja
└── compose/
    └── compose.yaml
```

## Before: run it locally

Build the dev-local image and run the stack exactly as checked in:

```bash
podman build -t localhost/myapp:dev .
docker compose -f compose/compose.yaml up
```

## compose/compose.yaml

```yaml
services:
  myapp:
    image: localhost/myapp:dev
    ports:
      - "8080:8080"
```

`localhost/myapp:dev` is a literal, runnable image reference — not a placeholder. This is the contract:
source files under `compose/` must work locally without any margot involvement.

## margo.yaml

```yaml
apiVersion: v1
id: com-example-myapp
name: myapp
version: "1.0.0"
appVersion: "2.3.1"
description: "myapp deployed via Compose"
repository: public.ecr.aws/g2n4p2m7/margo

compose:
  version: 1.0.0
  image:
    search: "localhost/myapp:dev"
    replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}"
```

- `search` — the literal string as it appears in `compose/compose.yaml`.
- `replace` — a Jinja2 template rendered from the same [manifest context](../margo-yaml.md#template-context)
  used for `app.yaml.jinja`. `{{ manifest.appVersion }}` resolves to `2.3.1`.

Because `replace` is a template rather than a static string, bumping `appVersion` in `margo.yaml`
is the *only* edit needed to point every artifact at the new image tag — the `image` block itself
never needs to change.

## Build

```bash
margot build
```

margot copies `compose/` to a temp dir, substitutes manifest placeholders, renders and applies the
`image` search-and-replace, and writes the tarball to `.dist/`:

```text
.dist/
└── 1.0.0/
    └── myapp-1.0.0.tgz
```

## After: what's inside `.dist`

The archived `compose.yaml` inside `myapp-1.0.0.tgz` — note `localhost/myapp:dev` is gone:

```yaml
services:
  myapp:
    image: public.ecr.aws/g2n4p2m7/myapp:2.3.1
    ports:
      - "8080:8080"
```

The source file on disk (`compose/compose.yaml`) is untouched — the substitution happens only in
the temp copy that gets packaged. Your local dev loop (`podman build` + `docker compose up`
against `localhost/myapp:dev`) keeps working after `margot build` runs.

## Push

`margot push` reads the same `.dist/` layout `margot build` produced — no separate step needed:

```bash
margot push
```

This pushes the tarball to `public.ecr.aws/g2n4p2m7/margo:1.0.0` with artifact type
`application/vnd.org.margo.component.compose+json`.

## Bumping the version — no `image` edits needed

Release `2.0.0` of the deployed application requires touching only `appVersion`:

```yaml
appVersion: "2.4.0"
```

Re-running `margot build` renders `replace` again with the new context — the packaged
`compose.yaml` now points at `public.ecr.aws/g2n4p2m7/myapp:2.4.0`. The `image.search` /
`image.replace` block in `margo.yaml` is unchanged.

## Per-variant override

If the component declares `variants`, a variant's `image` block **fully replaces** the
component-level one — it does not merge:

```yaml
compose:
  version: 1.0.0
  image:
    search: "localhost/myapp:dev"
    replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}"
  variants:
    - name: default             # inherits the block above
    - name: addon-mosquitto
      image:                     # replaces it entirely for this variant
        search: "localhost/mosquitto:dev"
        replace: "public.ecr.aws/g2n4p2m7/mosquitto:{{ manifest.appVersion }}"
```

Building `--variant addon-mosquitto` searches `compose/addon-mosquitto/` for `localhost/mosquitto:dev`
only — the `localhost/myapp:dev` search from the component level does not apply to that variant.

!!! note
    An unmatched `search` string (declared but not found in any source file) produces a warning,
    not a build failure — the same posture as other unresolved placeholders. An undefined Jinja
    variable in `replace`, however, is a hard error at build time.
