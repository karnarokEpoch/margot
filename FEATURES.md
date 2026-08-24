# margot — Feature Plan

Developer CLI for building and publishing Margo application packages.

> **Testing:** see [TESTING.md](TESTING.md) for the test plan, structure, and coverage requirements.

---

## Tech Stack

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python ≥ 3.12 | Matches existing tooling |
| Package manager | uv | Already used in all sub-projects |
| CLI framework | Typer (built on Click) | Rich integration, type hints → CLI args |
| Output | rich | Already used in tasks/ |
| Config | dynaconf | Flag > env > config file layering, TOML/YAML support |
| OCI push/pull | **oras-py** (`pip install oras`) | See note below |
| Schema validation | linkml | Already used in tasks/validation/ |

**Why Typer over raw Click?** Type annotations become CLI args automatically, keeping
code minimal. Rich output integration is first-class.

**Why dynaconf over custom parser?** Supports `settings.toml` + `settings.local.toml` +
env vars (`MARGOT_` prefix) + CLI flags with priority layering, no bespoke code needed.

### OCI library: oras-py vs ORAS CLI subprocess

**Short answer: use oras-py, keep ORAS CLI as a documented fallback dep.**

Options evaluated:

- `oras` (PyPI: `oras-py`) — official Python SDK from the ORAS project. Supports push,
  pull, manifest fetch, login/logout, custom media types, annotations. Actively maintained
  (CNCF sandbox). As of 0.2.x the default CLI was removed; it is now a pure library.
  **This is the right choice.**
- `opencontainers` (PyPI) — Python port of the Go OCI spec types + a Reggie HTTP client.
  Low-level, requires building all push/pull logic manually. Not worth it.
- ORAS CLI subprocess — works but adds an external binary dependency, harder to control
  credential lifecycle, no programmatic access to responses.

**oras-py key APIs used:**

```python
from oras.client import OrasClient
client = OrasClient(hostname="public.ecr.aws")
client.login(username="AWS", password=token, hostname="public.ecr.aws")
client.push(files=[("margo.yaml", "application/vnd.margo.app.description.v1+yaml")],
            target="public.ecr.aws/org/repo:tag",
            manifest_annotations={...})
client.pull(target="public.ecr.aws/org/repo:tag", outdir=".run/1.0.0")
# manifest fetch:
client.remote.get_manifest("public.ecr.aws/org/repo:tag")
```

---

## Configuration

### Priority (highest → lowest)

1. CLI flags
2. Environment variables (`MARGOT_` prefix, e.g. `MARGOT_REGISTRY`)
3. `margot.toml` in project directory
4. `~/.config/margot/config.toml` (user defaults)

### Key config keys

```toml
registry = "public.ecr.aws"        # OCI registry base URL
repository = "org/repo/app-name"    # repository path
build_dir = ".dist"                 # local build output
run_dir = ".run"                    # local pull output
```

### Project descriptor file: `margo.yaml`

Single source of truth for a Margo application project, located at the project root.
Replaces the old `publish_metadata.json`. Read by `margot build` and `margot push`.

**Format:**

```yaml
apiVersion: v1                     # margot config schema version (not Margo spec version)
id: myapp                          # stable machine identifier for the application (required)
name: myapp                        # human-readable application name (used in tarball filenames, OCI annotations)
version: "1.0.0"                   # margo artifact OCI tag — also manifest version in Jinja2 context (required)
appVersion: "2.3.1"               # version of the deployed application (optional, like Helm's appVersion)
description: "Human-readable description of the application"
directory: margo                   # path to the margo artifact source dir (optional, default: margo)
repository: public.ecr.aws/g2n4p2m7/margo   # default OCI repository for all artifacts (optional)
annotations:                       # arbitrary key/value pairs, optional
  opentelemetry.io/instrumented: "true"
author:                            # optional list
  - name: Alice Example
    email: alice@example.com
organization:                      # optional list
  - name: Example Corp
    site: https://example.com

compose:
  directory: compose               # path to the compose source dir (optional, default: compose)
  version: 1.0.0                   # OCI tag for the compose artifact(s) — used as base when variants are declared
  repository: public.ecr.aws/g2n4p2m7/margo   # optional override; falls back to global repository
  image:                            # optional — dev-local image ref swap, applied at build time
    search: "myapp:dev"             # literal string as it appears in compose.yaml (must be runnable locally as-is)
    replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}"   # Jinja2 template — rendered from manifest context
  variants:
    - name: default                # maps to compose/default/ subdir
      # version omitted — derived as 1.0.0+compose-default → OCI tag 1.0.0_compose-default
      component: myapp-compose-default   # optional stable component name; defaults to {id}-compose-{name}
      # no image override here — inherits the component-level image block above
    - name: simple                 # maps to compose/simple/
      version: 1.0.0+compose-simple    # explicit version overrides derivation ('_' encodes '+' in OCI tag)
    - name: addon-mosquitto        # maps to compose/addon-mosquitto/
      image:                        # per-variant override — replaces the component-level image block, not merged
        search: "mosquitto:dev"
        replace: "public.ecr.aws/g2n4p2m7/mosquitto:{{ manifest.appVersion }}"

quadlet:
  directory: quadlet               # optional, default: quadlet
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
  image:
    search: "myapp:dev"
    replace: "public.ecr.aws/g2n4p2m7/myapp:{{ manifest.appVersion }}"
  variants:
    - name: default                # version omitted — derived as 1.0.0+quadlet-default
    - name: simple                 # version omitted — derived as 1.0.0+quadlet-simple
```

**Field rules:**

- `apiVersion` — required. Currently `v1`.
- `id` — required. Stable machine identifier for the application. Used as the base for derived component name defaults. Must not change across releases. Exposed as `manifest.id` in `app.yaml.jinja` templates.
- `name` — required. Human-readable application name. Used in tarball filenames (`<name>-<version>.tgz`) and OCI title annotation. Exposed as `manifest.name` in templates.
- `version` — required. Margo artifact OCI tag and manifest version. Exposed as `manifest.version` in templates. Must be a valid OCI tag; SemVer recommended.
- `appVersion` — optional. Version of the deployed application (like Helm's `appVersion`). Not validated as SemVer. Exposed as `manifest.appVersion` in templates (empty string if absent).
- `description` — required. Used in OCI description annotation. Exposed as `manifest.description` in templates.
- `directory` — optional. Path to the margo artifact source directory. Default: `margo`. Exposed as `manifest.directory` in templates.
- `repository` — optional. Default OCI repository for all artifacts. Overridable per component. Exposed as `manifest.repository` in templates. Falls back to tool config / CLI / env var.
- `annotations` — optional. Arbitrary key/value pairs. Exposed as `manifest.annotations` dict in templates.
- `author` — optional list of `{name, email}` objects. Exposed as `manifest.author` in templates.
- `organization` — optional list of `{name, site}` objects. Exposed as `manifest.organization` in templates.
- `compose.version`, `quadlet.version` — required per component if that component is built. Used as the **base** version: directly as OCI tag when no variants are declared; as the derivation base for variant versions when variants are declared.
- `compose.directory`, `quadlet.directory` — optional. Defaults to the component type name (`compose`, `quadlet`).
- `repository` at component level — optional; overrides the global top-level `repository`.
- `variants` — list of `{name[, version, component, image]}` objects. Required if variants exist; `--variant all` expands to this list. `--variant NAME` selects one entry by name.
  - All variant names map to `<component.directory>/<name>/`.
  - `version` — optional per variant. When omitted, derived as `<component-version>+<type>-<variant-name>` (e.g. component `version: 2.1.0`, type `compose`, name `default` → `2.1.0+compose-default` → OCI tag `2.1.0_compose-default`). When present, used as-is.
  - `component` — optional per-variant stable component name. Defaults to `{id}-{type}-{name}` (e.g. `myapp-compose-default`). Developer-owned: margot computes the default but never overwrites an explicitly set value.
  - For flat components (no `variants` declared), `component` at the component level defaults to `{id}-{type}` (e.g. `com-example-nginx-quadlet`).
  - Variant names that collide with reserved field names (`directory`, `repository`, `variants`, `version`, `tag`, `ref`, `component`) are rejected at parse time with a clear error.
- `image` (compose/quadlet only) — optional `{search, replace}` block for swapping a dev-local container image reference for the environment-appropriate one at build time.
  - `search` — a literal string (not a regex), exactly as it appears in the component's source text file(s). The source file must be a real, runnable artifact as checked in.
  - `replace` — a **Jinja2 template string**, rendered with the same manifest context used for `app.yaml.jinja`. Undefined variables are a hard build error (`StrictUndefined`).
  - May be declared at the component level and/or per-variant. A variant's `image` block **fully overrides** (does not merge with) the component-level one.
  - Optional — a component/variant with no `image` block gets no image substitution.
  - Unmatched `search` string (declared but not found in any source file) produces a warning, not a hard failure.
- Version strings with `+` are stored with `+` in `margo.yaml`. margot converts `+` to `_` when producing OCI tags, since `+` is not a valid OCI tag character. Write versions with `+` — the conversion is automatic.

**Missing `margo.yaml`** → clear error: `"margo.yaml not found in current directory. Run margot init or create it manually."` (exit 1).

---

## Application Project Layout

A Margo application project that margot operates on has this structure:

```
<project-root>/
├── margo.yaml                     # project descriptor (required)
├── margo/                         # margo artifact source (path set by top-level directory, default: margo)
│   ├── app.yaml                   # Margo app descriptor — static (use one or the other, not both)
│   ├── app.yaml.jinja             # Margo app descriptor — Jinja2 template (rendered to app.yaml at build time)
│   └── resources/                 # optional supporting files
│       ├── icon.png
│       ├── license.txt
│       ├── release-notes.md
│       └── description.md
├── compose/                       # compose source (path set by compose.directory)
│   ├── compose.yaml               # flat layout — used when no variants declared
│   ├── .rsyncignore               # optional ignore patterns (flat layout only)
│   ├── default/                   # 'default' variant subdir (when variants declared)
│   │   ├── compose.yaml
│   │   └── .rsyncignore           # optional ignore patterns (per-variant)
│   ├── simple/                    # named variant subdir
│   │   ├── compose.yaml
│   │   └── .rsyncignore
│   └── addon-mosquitto/
│       └── compose.yaml
└── quadlet/                       # quadlet source (path set by quadlet.directory)
    ├── myapp.container            # flat layout — used when no variants declared
    ├── default/                   # 'default' variant subdir (when variants declared)
    │   └── myapp.container
    ├── simple/
    │   └── myapp.container
    └── addon-mosquitto/
        └── myapp.container
```

**No variants declared (flat layout):** if `variants` is absent from the component in
`margo.yaml`, the component directory is built as a single artifact using
`compose.version` / `quadlet.version`. No subdirectory logic applies.

**Variants declared:** the `variants` list in `margo.yaml` is authoritative — only declared
variants are built. All variant names (including `default`) map to `<component.directory>/<name>/`.
There is no implicit root mapping — when variants are declared, every variant lives in its own subdir.

**`.rsyncignore`:** if present in the source dir (or variant subdir), its patterns are applied
during the tree copy step. One file per source dir; applies to that dir only.

---

## Package Types

### `margo`

- Source: `margo/` directory (path set by top-level `directory` in `margo.yaml`, default: `margo`)
- Output: OCI artifact tagged with the top-level `version`
- Artifact type: `application/vnd.margo.app.v1+json`
- Layers: `app.yaml`, `resources/` (icon, license, release-notes, description)
- Media types per file:
  - `app.yaml` → `application/vnd.margo.app.description.v1+yaml`
  - `resources/icon.png` → `application/vnd.margo.app.icon.v1+png`
  - `resources/license.txt` → `application/vnd.margo.app.license.v1+plain`
  - `resources/release-notes.md` → `application/vnd.margo.app.releaseNotes.v1+markdown`
  - `resources/description.md` → `application/vnd.margo.app.descriptionFile.v1+markdown`
- Build step: copy source → output dir, then render `app.yaml`:
  - File resolution (checked in order):
    1. Both `app.yaml.jinja` and `app.yaml` present → **hard error** (fail build, clear message).
    2. `app.yaml.jinja` present → render with Jinja2 `StrictUndefined`, write as `app.yaml` in output. The `.jinja` source is **not** copied to the output.
    3. `app.yaml.jinja` absent → copy `app.yaml` verbatim. No substitution.
  - Jinja2 template context (read-only, derived from `margo.yaml`):

    ```
    manifest.id
    manifest.name
    manifest.version
    manifest.appVersion          # empty string if absent
    manifest.description
    manifest.directory
    manifest.repository
    manifest.annotations         # dict
    manifest.author              # list
    manifest.organization        # list

    manifest.compose.directory
    manifest.compose.repository
    manifest.compose.version
    manifest.compose.tag         # version with '+' replaced by '_' (flat only)
    manifest.compose.ref         # repository:tag (flat only)
    manifest.compose.component   # derived component name (flat only: {id}-compose)
    manifest.compose.variants    # ordered list of variant objects (see below)
    manifest.compose.<name>      # direct access by variant name

    manifest.quadlet.*           # same shape as compose
    ```

  - Variant object fields: `name`, `version`, `tag` (OCI-safe, `+`→`_`), `ref` (`repository:tag`), `repository`, `component`.
  - Flat components (no `variants` declared) expose a single synthetic variant entry in `variants` so templates iterate uniformly, plus `tag`, `ref`, and `component` directly on the component context.
  - Component name defaults:
    - Flat: `{id}-{type}` (e.g. `com-example-nginx-quadlet`)
    - With variants: `{id}-{type}-{variant-name}` (e.g. `myapp-compose-default`)
  - Unresolved Jinja2 variables cause a hard build failure (`StrictUndefined`).

### `compose`

- Source: `compose/` directory (path set by `compose.directory` in `margo.yaml`)
- Output: `.tgz` tarball, OCI artifact tagged with the variant's `version`
- Artifact type: `application/vnd.org.margo.component.compose+json`
- Layer: `<name>-<version>.tgz` → `application/vnd.org.margo.component.compose.tar+gzip`
- Annotations: `org.margo.component.type=compose`, `org.margo.component.version`, OCI image annotations
- Build step: copy source dir → temp dir (respecting `.rsyncignore`), substitute placeholders in all text files, apply the component/variant's `image` search/replace (if declared — see `margo.yaml` `image` field rules above), `tar -czf` (pure Python, no host binaries)
- Variant source resolution:
  - No `variants` in `margo.yaml` → use component directory root, tag from `compose.version`
  - `name: default` → use `<compose.directory>/default/`
  - Any other name → use `<compose.directory>/<name>/`
- `.rsyncignore` respected if present in source dir
- Tarball structure: the `.tgz` contains a single top-level directory named after
  `margo.yaml`'s top-level `name` field (`MargoYaml.name`), so extracting produces
  `<name>/<file>` rather than dumping files directly into the extraction target.

- Source: `quadlet/` directory (path set by `quadlet.directory` in `margo.yaml`)
- Output: `.tgz` tarball, OCI artifact tagged with the variant's `version`
- Artifact type: `application/vnd.org.margo.component.quadlet+json`
- Layer: `<name>-<version>.tgz` → `application/vnd.org.margo.component.quadlet.tar+gzip`
- Annotations: same pattern as compose with `type=quadlet`
- Build step: identical to compose
- Variant source resolution: same rules as compose (default → root, named → subdir)
- `.rsyncignore` respected if present in source dir
- Tarball structure: same as compose — a single top-level `<name>/` directory
  wraps the contents.

---

## Commands

### `margot build`

Build one or all package types into `build_dir`.

```
margot build [--type margo|compose|quadlet|all] [--version VERSION]
               [--registry REG] [--repository REPO] [--build-dir DIR]
               [--variant VARIANT]
```

**Logic per type:**

**margo:**

1. Read `margo.yaml` from CWD for versions, directories, and repository
2. Copy source `directory` → `<build_dir>/<version>/margo/` (pure Python, no rsync)
3. Render `app.yaml`:
   - Both `app.yaml.jinja` and `app.yaml` present → hard error (exit 1).
   - `app.yaml.jinja` present → render with Jinja2 `StrictUndefined`, write output as `app.yaml`. The `.jinja` source is not included in output.
   - `app.yaml.jinja` absent → copy `app.yaml` verbatim. No substitution.

**compose / quadlet:**

1. Read `margo.yaml`
2. Copy source dir → temp dir (respecting `.rsyncignore` if present)
3. Substitute placeholders in all text files (registry/repo URL, image tags)
4. `tar -czf <build_dir>/<version>/<name>-<version>.tgz` (pure Python tarfile, no tar binary)
5. Variant handling: if `--variant all`, build every variant declared in `margo.yaml`; if `--variant NAME`, build the named variant only

**all:** run margo + compose (all variants) + quadlet (all variants) in sequence

**Tag naming convention (MANDATORY):**
All tags pushed by margot MUST be valid OCI tags. Version strings with `_` are accepted
and stored as-is — `_` encodes `+` (SemVer build metadata separator) per the Margo OCI
distribution spec, since `+` is not a valid OCI tag character.

```
<version>            e.g. 1.3.0           ← margo artifact
<version>            e.g. 1.3.0           ← compose artifact (no variant)
<version>_<variant>  e.g. 1.3.0_simple    ← compose artifact (variant)
<version>_<variant>  e.g. 1.3.0_simple    ← quadlet artifact (variant)
```

The artifact type (`margo`, `compose`, `quadlet`) is encoded in the OCI `artifactType`
field, NOT in the tag. Multiple artifacts at different tags can coexist in the same
repository — the consumer selects by tag + artifact type.

The `-compose` / `-quadlet` / `-margo-manifest` suffix pattern from the old invoke
tasks is **removed**. Artifact type disambiguation happens via `artifactType` field.

---

### `margot push`

Push built artifacts to OCI registry via ORAS.

```
margot push [--type margo|compose|quadlet|all]
              [--registry REG] [--repository REPO] [--build-dir DIR]
              [--variant VARIANT]
```

**Prereq check:** validate the tag is SemVer before doing anything else. Fail fast.

**margo push:**

```python
client.push(
    files=[
        ("margo.yaml", "application/vnd.margo.app.description.v1+yaml"),
        ("README.md",  "application/vnd.margo.app.descriptionFile.v1+markdown"),
        ("resources/icon.png",         "application/vnd.margo.app.icon.v1+png"),
        ("resources/license.txt",      "application/vnd.margo.app.license.v1+plain"),
        ("resources/release-notes.md", "application/vnd.margo.app.releaseNotes.v1+markdown"),
        ("resources/description.md",   "application/vnd.margo.app.descriptionFile.v1+markdown"),
    ],
    target=f"{registry}/{repo}:{tag}",
    manifest_config={"mediaType": "application/vnd.margo.app.v1+json", ...},
)
```

**compose / quadlet push:**

```python
client.push(
    files=[(archive_path, "application/vnd.org.margo.component.compose.tar+gzip")],
    target=f"{registry}/{repo}:{tag}",
    manifest_config={"mediaType": "application/vnd.org.margo.component.compose+json"},
    manifest_annotations={
        "org.margo.component.type": "compose",
        "org.margo.component.version": tag,
        "org.opencontainers.image.title": name,
        "org.opencontainers.image.description": description,
    },
)
```

**Registry auth:** credentials must be active. Run `margot auth login` before pushing.

---

### `margot pull`

Pull OCI artifact layers to a local directory without extraction.

```
margot pull <uri> [--output DIR]
```

`<uri>` is the full OCI reference (e.g. `public.ecr.aws/g2n4p2m7/margo:1.0.0`).
`--output` / `-o` defaults to `.` (current directory).

No `--type` / `--version` / `--registry` / `--repository` flags — the URI is fully
caller-provided, same shape as `fetch`. No SemVer validation: `pull` retrieves
arbitrary existing artifacts. Auth: anonymous only.

**Logic:**

1. Validate URI via `domain/uri.py` (`validate_uri`).
2. Fetch manifest via `OrasClient.get_manifest(uri)`.
3. Detect artifact type from the `artifactType` manifest field:
   - `application/vnd.margo.app.v1+json` → margo
   - `application/vnd.org.margo.component.compose+json` → compose
   - `application/vnd.org.margo.component.quadlet+json` → quadlet
   - anything else → unknown (oras default naming)
4. Pull layers via `OrasClient.pull(uri=uri, outdir=outdir)`.
5. For compose/quadlet: rename the payload file if a better name can be resolved
   from the layer's `org.opencontainers.image.title` annotation, or from
   manifest-level `org.opencontainers.image.title` + `org.opencontainers.image.version`
   annotations (`<title>-<version>.tgz`).
6. Report each written file path. If no layers are pulled, report that.

No extraction — `.tgz` blobs are written as-is.

---

### `margot fetch`

Fetch and inspect a remote artifact without full pull to disk.

```
margot fetch <uri>
```

`<uri>` is the full OCI reference: `registry/repository:tag`
(e.g. `public.ecr.aws/g2n4p2m7/belden-margo:1.0.1-victorialogs-margo-manifest`).

No flags for registry / repository / version — the URI is fully caller-provided.
No SemVer validation: `fetch` inspects arbitrary existing artifacts, including legacy
tags. SemVer enforcement is scoped to `build` and `push`.

**Logic:**

```python
client = OrasClient(hostname=<parsed_registry>)
manifest = client.remote.get_manifest(uri)
```

**Output:** raw manifest JSON, pretty-printed to stdout via `rich`.
No table, no filtering — display whatever the registry returns.

---

### `margot verify`

Validate the Margo **application description** (`app.yaml`, or `app.yaml.jinja` when the
project templates it) against the upstream Margo spec LinkML schema, and optionally
against margot's curated recommended schema.

`margo.yaml` is not validated by this command — it is margot's build anchor, not a Margo
spec document.

```
margot verify [--project-dir PATH] [--manifest PATH]
              [--schema PATH] [--recommended-schema PATH]
              [--recommend] [--strict]
```

**Manifest resolution:**

1. `--manifest` if given — may point at an `app.yaml` or an `app.yaml.jinja`.
2. Otherwise `margo.yaml` is loaded from `--project-dir` (default `.`) and its
   `directory` field is searched for `app.yaml.jinja`, then `app.yaml`. Both present is an
   error; neither present is an error.
3. A `.jinja` descriptor is rendered to a **temporary file** with the same context and
   `StrictUndefined` behavior `build` uses, and the rendered file is what gets validated.
   `verify` never reads `<build_dir>` and never requires a prior `build`.

**Schema A — upstream Margo spec (always runs):**

1. Vendored at `src/margot/schemas/application-description.linkml.yaml`, pinned to an
   upstream commit (the spec is still draft). Overridable with `--schema`.
2. Validate with `linkml.validator` using:
   - `JsonschemaValidationPlugin(closed=True)` — no unexpected fields
   - `RecommendedSlotsPlugin()` — warns on missing recommended fields
   - `MaximumCardinalityPlugin` — enforce cardinality constraints
3. Any error fails the run (exit 1).
4. The pinned draft commit is always printed, so results are never mistaken for
   validation against a stable spec.

**Schema B — margot recommended (`--recommend`):**

- Vendored at `src/margot/schemas/margo-recommended.linkml.yaml`, overridable with
  `--recommended-schema`. Not loaded or run at all without `--recommend`.
- Default: a lint pass — findings are reported, exit code unaffected.
- With `--strict`: a contract — any finding fails the run (exit 1).
- When both schemas run, findings are printed under separate labeled sections.

**Output:** plain CI-check-style pass/fail lines, pipeable into CI logs. No tables, no
panels — visual inspection of a descriptor is `margot describe`.

Exit codes: 0 = passed, 1 = any error.

**Remote artifact reachability (`--remote`)** is backlog, not implemented — see
`ROADMAP.md`.

---

### `margot describe`

Render the Margo application description as a structured, visual view: rich panels,
trees and tables organizing the raw descriptor for human review. Read-only, no schema
validation, no network.

```
margot describe [--project-dir PATH] [--manifest PATH]
                [--section metadata|profiles|parameters|config|extensions]
```

**Descriptor resolution:** identical to `verify` — `--manifest`, else `margo.yaml`
`directory` → `app.yaml.jinja` (rendered to a temp file) or `app.yaml`. Never reads
`<build_dir>`, never requires a prior `build`.

**Blocks rendered:** application identity (`id`, `kind`, `metadata.name`,
`metadata.version`, `metadata.description`), catalog (`metadata.catalog`), deployment
profiles as a tree (`deploymentProfiles[]` → `components[]` → `properties`) with
`requiredResources`, parameters as a table (top-level `parameters` map joined with
`configuration.schema` through `configuration.sections[].settings[]` for data type and
constraints), the configuration layout as a tree, and `x-placeholder-extensions` when
present. `--section` limits the output to selected blocks.

The Margo spec permits plenty of odd-but-valid structures — a parameter no `Setting`
refers to, a component without a `repository`, a profile with no components. `describe`
renders them faithfully; judging them is `verify`'s job.

**Not provided:** no `--json`, no `--yaml`, no plain-text mode. Visual output only.

Exit codes: 0 always, except 1 when the descriptor cannot be loaded (missing, both
`app.yaml` and `app.yaml.jinja` present, unresolved Jinja2 variable, unparseable YAML, or
`kind` not `ApplicationDescription`) — in which case the error points at `margot verify`.

---

## Project Structure

Follows a **layered architecture**: CLI → Services → Domain / Infra.
Dependency rule: inner layers never import outer ones. Domain has no I/O.

```
margot/
├── pyproject.toml
├── margot.toml.example            # example config
├── FEATURES.md                      # this file
└── src/
    └── margot/
        ├── __init__.py
        ├── main.py                  # Typer app + command registration only
        ├── config.py                # dynaconf Settings (cross-cutting)
        │
        ├── domain/                  # pure logic — zero I/O, zero framework imports
        │   ├── tags.py              # semver validation
        │   ├── metadata.py          # margo.yaml dataclasses + parser
        │   ├── validation.py        # ValidationFinding, VerifyResult
        │   ├── describe.py          # describe display models + parameter/schema join
        │   └── models.py            # PackageType enum, BuildTarget, etc.
        │
        ├── services/                # business logic — orchestrates domain + infra
        │   ├── build.py             # build flow (rsync, sed, tar)
        │   ├── push.py              # push flow (credential check → oci.push)
        │   ├── pull.py
        │   ├── fetch.py
        │   ├── verify.py            # descriptor resolution + linkml validation
        │   ├── describe.py          # descriptor resolution + display model build
        │   └── auth.py              # login/logout orchestration
        │
        ├── infra/                   # I/O adapters — no business logic
        │   ├── oci.py               # oras-py wrapper (push/pull/fetch/login/logout)
        │   ├── credentials.py       # ~/.config/margot/credentials.toml R/W
        │   ├── templating.py        # app.yaml.jinja rendering (shared by build/verify/describe)
        │   └── filesystem.py        # tree copy, placeholder substitution, tar, yaml, temp files
        │
        ├── schemas/                 # vendored LinkML schemas (data, not code)
        │   ├── application-description.linkml.yaml   # upstream Margo spec, pinned commit
        │   └── margo-recommended.linkml.yaml         # margot curated recommendations
        │
        ├── commands/                # CLI layer — parse args, call service, render output
        │   ├── build.py
        │   ├── push.py
        │   ├── pull.py
        │   ├── fetch.py
        │   ├── verify.py            # plain pass/fail lines
        │   ├── describe.py          # rich panels / trees / tables
        │   └── auth.py              # margot auth {login,logout,status}
        │
        └── validation/              # linkml-specific, called by services/verify.py
            ├── linkml_runner.py     # only module allowed to import linkml
            ├── error_formatter.py   # findings → plain strings / row tuples
            └── max_cardinality.py
```

### Layer responsibilities

| Layer | Rule | Imports |
|---|---|---|
| `commands/` | Parse args, call one service, render output. No logic, no I/O. | `services/`, `config` |
| `services/` | Orchestrate the feature flow. No CLI, no rich output. | `domain/`, `infra/`, `validation/` |
| `domain/` | Pure functions and dataclasses. Raise `ValueError` on bad input. | stdlib only |
| `infra/` | All I/O (filesystem, OCI, ECR, credentials file, templating). | `domain/`, stdlib, third-party |
| `validation/` | LinkML runner and formatters. Returns data, never `rich` objects. | `domain/`, `infra/` |

---

## Key Implementation Notes

### Version handling

- The margo artifact version comes from the top-level `version` field in `margo.yaml`.
- Component versions (`compose.version`, `quadlet.version`) are the **base** for their artifacts.
- CLI `--version` overrides the version for the selected component type.
- Variant `version` is optional: when absent, derived as `<component-version>+<type>-<variant-name>`. When present, used as-is.
- Tag format: `+` in versions is stored as `+` in `margo.yaml` and converted to `_` for OCI tags.

### OCI operations (oras-py)

All OCI push/pull/fetch/login/logout go through `oras.client.OrasClient`. No subprocess
calls to the ORAS CLI binary. Credential expiry check runs before every registry
operation (push, pull, fetch). Rich `Progress` for long operations.

### Semver validation

Every tag value provided by the user (via flag, config, or `margo.yaml`) is
validated against the OCI tag rules before any operation proceeds. Tags are
normalized (`_`→`+`) for SemVer semantic validation but stored as-is. Reject
immediately with a clear error. The tool does not construct tags with suffixes — the caller owns
the tag string entirely.

### Error handling

- Missing `margo.yaml` → clear error: `"margo.yaml not found in current directory. Run margot init or create it manually."` (exit 1)
- Invalid OCI tag → reject immediately before any build/push step
- Credentials expired or near-expiry → warn or hard-fail with `margot auth login` hint
- oras-py push/pull failure → surface exception message, exit 1
- Validation errors → rich table, exit 1

### Variant discovery

Variants are declared in `margo.yaml` — on-disk discovery is not used. For
`build --type compose --variant all`: build every variant in the `variants` list.
For `--variant NAME`: build the single entry matching that name.

Source directory resolution:
- No `variants` key → component directory root (e.g. `compose/`)
- `name: default` → `<component.directory>/default/`
- Any other name → `<component.directory>/<name>/` (e.g. `compose/simple/`)

### `.rsyncignore`

If present in source dir (or variant subdir), its patterns are applied during the tree
copy step via the `shutil.copytree` ignore callable. One file per source dir; applies to
that dir only. Filename kept for continuity with the old invoke tasks even though `rsync`
is no longer used.

### Config file example (`margot.toml`)

```toml
registry = "public.ecr.aws"
repository = "org/myapp"
build_dir = ".dist"
run_dir = ".run"
```

### `margot auth login`

Authenticate with an OCI registry and persist credentials.

```
margot auth login REGISTRY [--username USER] [--password-stdin]
                  [--expiry-hours N]
```

**How it works:**

oras-py handles the full OCI auth challenge-response flow. For any registry (including
AWS ECR), passing username + password is sufficient — oras-py negotiates the correct
token exchange automatically in response to `Www-Authenticate` headers. No registry-
specific code is needed in margot.

```python
client.login(username=user, password=password, hostname=registry)
```

oras-py stores credentials via the configured credential store (same as Docker/Podman).

**ECR:** pass `--username AWS` and the token from `aws ecr get-login-password` (or
`aws ecr-public get-login-password`) as the password. oras-py's `EcrAuth` backend
handles ECR's challenge-response automatically. No boto3 dependency in margot.

**Credential expiry tracking (`--save-expiry`):**
Persist the expiry timestamp to `~/.config/margot/credentials.toml`:

```toml
[registries."public.ecr.aws"]
expires_at = "2026-06-26T23:00:00Z"
```

Every command that calls the registry checks this file first. If `now >= expires_at - 1 hour`,
print a warning and optionally prompt to re-login.

---

### `margot auth logout`

Remove stored credentials for a registry.

```
margot auth logout REGISTRY
```

```python
client.logout(hostname=registry)
```

Also removes the expiry entry from `~/.config/margot/credentials.toml`.

---

### Credential Expiry — Design

**Problem:** ECR tokens expire every 12 hours. oras-py gives no proactive signal — the
caller only finds out when a push/pull fails mid-operation.

**Solution — proactive expiry check before any registry operation:**

```python
def check_credentials(registry: str) -> None:
    expiry = load_expiry(registry)  # from ~/.config/margot/credentials.toml
    if expiry is None:
        return  # no expiry tracked, proceed
    remaining = expiry - datetime.now(UTC)
    if remaining <= timedelta(0):
        raise CredentialsExpiredError(f"Credentials for {registry} expired. Run: margot auth login")
    if remaining < timedelta(hours=1):
        console.print(f"[yellow]Warning: credentials for {registry} expire in {remaining}[/yellow]")
```

This runs before every push call. `check_credentials` is in `infra/credentials.py`.

- Helm packaging (handled by helm CLI directly)
- Container image build / push
- Version bumping / release management
- CI/CD pipeline integration
