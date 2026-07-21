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
name: myapp                        # application name (used in tarball filenames, OCI annotations)
appVersion: "1.0.0"                # application version — used for <app_tag> placeholder substitution (optional)
description: "Human-readable description of the application"
annotations:                       # arbitrary key/value pairs, optional
  opentelemetry.io/instrumented: "true"
maintainers:                       # optional list
  - name: Alice Example
    email: alice@example.com

margo:
  directory: margo                 # path to the margo artifact source dir (contains app.yaml + resources/)
  version: 1.0.0                   # OCI tag for the margo artifact (must be valid OCI tag; SemVer recommended)
  repository: public.ecr.aws/g2n4p2m7/margo   # OCI repository for this component (overrides global)

compose:
  directory: compose               # path to the compose source dir (flat or variant subdirs)
  version: 1.0.0                   # OCI tag for the compose artifact(s) — used only when no variants
  repository: public.ecr.aws/g2n4p2m7/margo   # optional override; falls back to global repository
  variants:
    - name: default                # reserved name — maps to compose/default/ subdir
      version: 1.0.0
    - name: simple                 # maps to compose/simple/
      version: 1.0.0_simple        # OCI tag for this variant ('_' encodes '+' per Margo OCI spec)
    - name: addon-mosquitto        # maps to compose/addon-mosquitto/
      version: 1.0.0_addon-mosquitto

quadlet:
  directory: quadlet               # path to the quadlet source dir
  version: 1.0.0
  repository: public.ecr.aws/g2n4p2m7/margo
  variants:
    - name: default                # reserved name — maps to quadlet/default/ subdir
      version: 1.0.0
    - name: simple                 # maps to quadlet/simple/
      version: 1.0.0_simple
```

**Field rules:**

- `apiVersion` — required. Currently `v1`.
- `name` — required. Used in tarball filenames (`<name>-<version>.tgz`) and OCI title annotation.
- `appVersion` — optional. Human-facing application version string. Not validated as SemVer. Used as the value for `<app_tag>` placeholder substitution. If absent, `<app_tag>` resolves to an empty string.
- `description` — required. Used in OCI description annotation.
- `margo.directory` — required. Default: `margo`.
- `margo.version`, `compose.version`, `quadlet.version` — required per component if that component is built. Used as the tag when no variants are declared.
- `repository` at component level — optional; overrides global `repository` from `margot.yaml` tool config (or CLI flag / env var).
- `variants` — list of `{name, version}` objects. Required if variants exist; `--variant all` expands to this list. `--variant NAME` selects one entry by name.
  - `name: default` is a **reserved name** but maps to `<component.directory>/default/` — a real subdir, not the component root.
  - All variant names (including `default`) map to `<component.directory>/<name>/`.
  - When `variants` is present, `compose.version` / `quadlet.version` is ignored — each variant carries its own `version`.
- Version strings with `_` are stored as-is in the OCI tag. The `_` encodes `+` (SemVer build metadata separator) per the Margo OCI distribution spec, since `+` is not a valid OCI tag character.

**Missing `margo.yaml`** → clear error: `"margo.yaml not found in current directory. Run margot init or create it manually."` (exit 1).

---

## Application Project Layout

A Margo application project that margot operates on has this structure:

```
<project-root>/
├── margo.yaml                     # project descriptor (required)
├── margo/                         # margo artifact source (path set by margo.directory)
│   ├── app.yaml                   # Margo app descriptor with placeholders (required)
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

- Source: `margo/` directory (path set by `margo.directory` in `margo.yaml`)
- Output: OCI artifact tagged with `margo.version`
- Artifact type: `application/vnd.margo.app.v1+json`
- Layers: `app.yaml`, `resources/` (icon, license, release-notes, description)
- Media types per file:
  - `app.yaml` → `application/vnd.margo.app.description.v1+yaml`
  - `resources/icon.png` → `application/vnd.margo.app.icon.v1+png`
  - `resources/license.txt` → `application/vnd.margo.app.license.v1+plain`
  - `resources/release-notes.md` → `application/vnd.margo.app.releaseNotes.v1+markdown`
  - `resources/description.md` → `application/vnd.margo.app.descriptionFile.v1+markdown`
- Build step: copy source → temp dir, then substitute placeholders in `app.yaml`:
  - `<app_tag>`, `<compose_tag>`, `<quadlet_tag>`, `<helm_chart_tag>`, `<margo_tag>`
  - `<app_tag>` → `appVersion` top-level field (empty string if absent)
  - `<margo_tag>` → `margo.version`
  - `<compose_tag>` → `compose.version` (or first variant's version if variants declared)
  - `<quadlet_tag>` → `quadlet.version` (or first variant's version if variants declared)

### `compose`

- Source: `compose/` directory (path set by `compose.directory` in `margo.yaml`)
- Output: `.tgz` tarball, OCI artifact tagged with the variant's `version`
- Artifact type: `application/vnd.org.margo.component.compose+json`
- Layer: `<name>-<version>.tgz` → `application/vnd.org.margo.component.compose.tar+gzip`
- Annotations: `org.margo.component.type=compose`, `org.margo.component.version`, OCI image annotations
- Build step: copy source dir → temp dir (respecting `.rsyncignore`), substitute placeholders in all text files, `tar -czf` (pure Python, no host binaries)
- Variant source resolution:
  - No `variants` in `margo.yaml` → use component directory root, tag from `compose.version`
  - `name: default` → use `<compose.directory>/default/`
  - Any other name → use `<compose.directory>/<name>/`
- `.rsyncignore` respected if present in source dir

### `quadlet`

- Source: `quadlet/` directory (path set by `quadlet.directory` in `margo.yaml`)
- Output: `.tgz` tarball, OCI artifact tagged with the variant's `version`
- Artifact type: `application/vnd.org.margo.component.quadlet+json`
- Layer: `<name>-<version>.tgz` → `application/vnd.org.margo.component.quadlet.tar+gzip`
- Annotations: same pattern as compose with `type=quadlet`
- Build step: identical to compose
- Variant source resolution: same rules as compose (default → root, named → subdir)
- `.rsyncignore` respected if present in source dir

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
2. Copy source `margo.directory` → `<build_dir>/<margo.version>/margo/` (pure Python, no rsync)
3. Substitute placeholders in `app.yaml` (pure Python string replace, no sed):
   - `<app_tag>`, `<compose_tag>`, `<quadlet_tag>`, `<helm_chart_tag>`, `<margo_tag>`
   - `<app_tag>` → `appVersion` top-level field (empty string if absent)
   - `<margo_tag>` → `margo.version`
   - `<compose_tag>` → `compose.version` (or first variant's version if variants declared)
   - `<quadlet_tag>` → `quadlet.version` (or first variant's version if variants declared)

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
margot push [--type margo|compose|quadlet|all] [--version VERSION]
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

**Registry auth:** credentials must be active. Run `margot login` before pushing.

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

Validate the margo application description and optionally check published artifacts.

```
margot verify [--manifest PATH] [--schema PATH]
                [--remote] [--version VERSION]
                [--registry REG] [--repository REPO]
```

**Local validation (always runs):**

1. Load `margo.yaml` (default: `margo/margo.yaml` or configurable)
2. Load LinkML schema (default: `margo-spec.yaml` alongside manifest)
3. Validate with `linkml.validator` using:
   - `JsonschemaValidationPlugin(closed=True)` — no unexpected fields
   - `RecommendedSlotsPlugin()` — warns on missing recommended fields
   - `MaximumCardinalityPlugin` — enforce cardinality constraints
4. Format errors using the existing `format_validation_error` pattern
5. Exit code 0 = valid, 1 = validation errors

**Remote check (`--remote` flag):**

- Call `oras manifest fetch` for each referenced component tag in the manifest
- Verify each referenced OCI tag is reachable and has the expected artifact type
- Report any 404 / wrong type as errors

**Output:** rich table of results per check (PASS / WARN / FAIL with details).

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
        │   └── models.py            # PackageType enum, BuildTarget, etc.
        │
        ├── services/                # business logic — orchestrates domain + infra
        │   ├── build.py             # build flow (rsync, sed, tar)
        │   ├── push.py              # push flow (credential check → oci.push)
        │   ├── pull.py
        │   ├── fetch.py
        │   ├── verify.py            # linkml validation + optional remote check
        │   └── auth.py              # login/logout + ECR token refresh
        │
        ├── infra/                   # I/O adapters — no business logic
        │   ├── oci.py               # oras-py wrapper (push/pull/fetch/login/logout)
        │   ├── credentials.py       # ~/.config/margot/credentials.toml R/W
        │   ├── filesystem.py        # rsync, tar, sed helpers
        │   └── ecr.py               # boto3 ECR token fetch
        │
        ├── commands/                # CLI layer — parse args, call service, render output
        │   ├── build.py
        │   ├── push.py
        │   ├── pull.py
        │   ├── fetch.py
        │   ├── verify.py
        │   ├── login.py
        │   └── logout.py
        │
        └── validation/              # linkml-specific, called by services/verify.py
            ├── linkml_runner.py
            ├── error_formatter.py
            └── max_cardinality.py
```

### Layer responsibilities

| Layer | Rule | Imports |
|---|---|---|
| `commands/` | Parse args, call one service, render output. No logic. | `services/`, `config` |
| `services/` | Orchestrate the feature flow. No CLI, no rich output. | `domain/`, `infra/`, `validation/` |
| `domain/` | Pure functions and dataclasses. Raise `ValueError` on bad input. | stdlib only |
| `infra/` | All I/O (filesystem, OCI, ECR, credentials file). | `domain/`, stdlib, third-party |
| `validation/` | LinkML runner and formatters. | `domain/`, `infra/` |

---

## Key Implementation Notes

### Version handling

- All versions default to values in `margo.yaml` (read from CWD)
- CLI `--version` overrides the version for the selected component type
- Individual component versions are declared per-component in `margo.yaml`; variants have their own `version` entry in the `variants` list
- Tag format: `<version>` for non-variant artifacts, `<version>_<variant>` for variant artifacts (stored with `_` encoding `+` per Margo OCI spec)

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
- Credentials expired or near-expiry → warn or hard-fail with `margot login` hint
- ECR auto-refresh failure → clear error, do not proceed
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

### `margot login`

Authenticate with an OCI registry and persist credentials.

```
margot login [--registry REG] [--username USER] [--password-stdin]
               [--ecr] [--region REGION]
               [--save-expiry]
```

**Standard login (any registry):**

```python
client.login(username=user, password=password, hostname=registry)
```

oras-py stores credentials via the configured credential store (same as Docker/Podman).

**ECR shortcut (`--ecr`):**
ECR tokens expire every **12 hours**. The `--ecr` flag automates token retrieval:

```python
import boto3
token = boto3.client("ecr-public", region_name=region).get_authorization_token()
password = base64.b64decode(token["authorizationData"]["authorizationToken"]).split(b":")[1]
client.login(username="AWS", password=password.decode(), hostname=registry)
```

**Credential expiry tracking (`--save-expiry`):**
Persist the expiry timestamp to `~/.config/margot/credentials.toml`:

```toml
[registries."public.ecr.aws"]
expires_at = "2026-06-26T23:00:00Z"
```

Every command that calls the registry checks this file first. If `now >= expires_at - 5min`,
print a warning and optionally auto-refresh if `--ecr` credentials are configured.

---

### `margot logout`

Remove stored credentials for a registry.

```
margot logout [--registry REG]
```

```python
client.logout(hostname=registry)
```

Also removes the expiry entry from `~/.config/margot/credentials.toml`.

---

### Credential Expiry — Design

**Problem:** ORAS (and oras-py) silently fail or give opaque errors when credentials
expire (ECR: 12h TTL). The caller has no signal until a push/pull fails mid-operation.

**Solution — proactive expiry check before any registry operation:**

```python
def check_credentials(registry: str) -> None:
    expiry = load_expiry(registry)  # from ~/.config/margot/credentials.toml
    if expiry is None:
        return  # no expiry tracked, proceed
    remaining = expiry - datetime.now(UTC)
    if remaining <= timedelta(0):
        raise CredentialsExpiredError(f"Credentials for {registry} expired. Run: margot login")
    if remaining < timedelta(minutes=5):
        console.print(f"[yellow]Warning: credentials for {registry} expire in {remaining}[/yellow]")
```

**Auto-refresh (opt-in):** if `auto_refresh = true` in config and registry is ECR,
re-run the ECR token flow automatically before the operation. Requires boto3 available
and AWS credentials configured.

---

## Out of Scope (v1)

- Helm packaging (handled by helm CLI directly)
- Container image build / push
- Version bumping / release management
- CI/CD pipeline integration
