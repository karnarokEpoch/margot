# margoctl — Feature Plan

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
env vars (`MARGOCTL_` prefix) + CLI flags with priority layering, no bespoke code needed.

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
2. Environment variables (`MARGOCTL_` prefix, e.g. `MARGOCTL_REGISTRY`)
3. `margoctl.toml` in project directory
4. `~/.config/margoctl/config.toml` (user defaults)

### Key config keys

```toml
registry = "public.ecr.aws"        # OCI registry base URL
repository = "org/repo/app-name"    # repository path
build_dir = ".dist"                 # local build output
run_dir = ".run"                    # local pull output
```

### Project metadata file: `publish_metadata.json`

Existing format, read from working directory. Contains per-component versions:

- `app`, `daemon`, `compose`, `helm-chart`, `margo`, `quadlet`
- `metadata.name`, `metadata.description`, `metadata.source`

---

## Package Types

### `margo`

- Source: `margo/` directory
- Output: OCI artifact tagged `<version>-margo-manifest`
- Artifact type: `application/vnd.margo.app.v1+json`
- Layers: `margo.yaml`, `README.md`, `resources/` (icon, license, release-notes, description)
- Media types per file:
  - `margo.yaml` → `application/vnd.margo.app.description.v1+yaml`
  - `README.md` → `application/vnd.margo.app.descriptionFile.v1+markdown`
  - `resources/icon.png` → `application/vnd.margo.app.icon.v1+png`
  - `resources/license.txt` → `application/vnd.margo.app.license.v1+plain`
  - `resources/release-notes.md` → `application/vnd.margo.app.releaseNotes.v1+markdown`
  - `resources/description.md` → `application/vnd.margo.app.descriptionFile.v1+markdown`
- Build step: rsync source → temp dir, then `sed` substitutions for version placeholders
  (`<app_tag>`, `<compose_tag>`, `<quadlet_tag>`, `<helm_chart_tag>`, `<margo_tag>`, `<margo_version>`)

### `compose`

- Source: `compose/` directory (or subdirs for variants)
- Output: `.tgz` tarball, OCI artifact tagged `<version>-compose`
- Artifact type: `application/vnd.org.margo.component.compose+json`
- Layer: `<name>-<tag>.tgz` → `application/vnd.org.margo.component.compose.tar+gzip`
- Annotations: `org.margo.component.type=compose`, `org.margo.component.version`, OCI image annotations
- Build step: rsync → temp dir, `sed` image tag substitution, `tar -czf`
- Variants supported: any subdirectory with a `compose.yaml` is a valid variant source
- Variant tag: caller provides a valid SemVer tag; margoctl validates it, tool does not impose naming
- `.rsyncignore` respected if present

### `quadlet`

- Source: `quadlet/` directory (or subdirs for variants)
- Output: `.tgz` tarball, OCI artifact tagged `<version>-quadlet`
- Artifact type: `application/vnd.org.margo.component.quadlet+json`
- Layer: `<name>-<tag>.tgz` → `application/vnd.org.margo.component.quadlet.tar+gzip`
- Annotations: same pattern as compose with `type=quadlet`
- Build step: identical to compose
- Variants: any subdirectory with `.container` files is a valid variant source
- Variant tag: caller provides a valid SemVer tag; margoctl validates it
- `.rsyncignore` respected if present

---

## Commands

### `margoctl build`

Build one or all package types into `build_dir`.

```
margoctl build [--type margo|compose|quadlet|all] [--version VERSION]
               [--registry REG] [--repository REPO] [--build-dir DIR]
               [--variant VARIANT]
```

**Logic per type:**

**margo:**

1. Read `publish_metadata.json` for default versions
2. `rsync -La` source margo dir → `<build_dir>/<app_version>/margo/`
3. `find ... sed -i` to substitute placeholders (registry, repo, version tags)

**compose / quadlet:**

1. Read `publish_metadata.json`
2. `rsync -La` source dir → temp dir (respecting `.rsyncignore`)
3. `find ... sed -i` substitutions (registry/repo URL, image tags)
4. `tar -czf <build_dir>/<app_version>/<name>-<tag>.tgz`
5. Variant handling: if `--variant all`, run once per variant subdir

**all:** run margo + compose (all variants) + quadlet (all variants) in sequence

**Tag naming convention (MANDATORY):**
All tags pushed by margoctl MUST be valid SemVer. This is a hard requirement — no
freeform strings, no dev suffixes, no deployment-type suffixes baked into the tag.

```
<semver>           e.g. 1.3.0           ← margo manifest
<semver>           e.g. 1.3.0           ← compose artifact
<semver>           e.g. 1.3.0           ← quadlet artifact
```

The artifact type (`margo`, `compose`, `quadlet`) is encoded in the OCI
`artifactType` field, NOT in the tag. Multiple artifacts at different tags can
coexist in the same repository — the consumer selects by tag + artifact type.

**Variant tags:** a variant (e.g. `simple`, `addon-mosquitto`) is represented as a
SemVer pre-release or build metadata label, or as a separate tag that is itself
valid SemVer. The tool must validate the tag with a semver regex before pushing.
Examples: `1.3.0`, `1.3.0-simple.1`, `1.3.0+addon-mosquitto`. Exact format TBD
by project convention, but the tool REJECTS any non-semver tag at input.

The `-compose` / `-quadlet` / `-margo-manifest` suffix pattern from the old invoke
tasks is **removed**. Artifact type disambiguation happens via `artifactType` field.

---

### `margoctl push`

Push built artifacts to OCI registry via ORAS.

```
margoctl push [--type margo|compose|quadlet|all] [--version VERSION]
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

**Registry auth:** credentials must be active. Run `margoctl login` before pushing.

---

### `margoctl pull`

Pull artifacts from OCI registry via ORAS.

```
margoctl pull [--type margo|compose|quadlet] [--version VERSION]
              [--registry REG] [--repository REPO] [--run-dir DIR]
```

**Logic:**

```python
client.pull(target=f"{registry}/{repo}:{tag}", outdir=f"{run_dir}/{app_version}")
```

Pulls each requested artifact type into the run directory.

---

### `margoctl fetch`

Fetch and inspect a remote artifact without full pull to disk.

```
margoctl fetch [--type margo|compose|quadlet] [--version VERSION]
               [--registry REG] [--repository REPO]
```

**Logic:**

```python
manifest = client.remote.get_manifest(f"{registry}/{repo}:{tag}")
```

Display: artifact type, layers (filename + media type + digest + size), annotations.

**Output (rich table):** tag, artifact type, layers, annotations.

---

### `margoctl verify`

Validate the margo application description and optionally check published artifacts.

```
margoctl verify [--manifest PATH] [--schema PATH]
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
margoctl/
├── pyproject.toml
├── margoctl.toml.example            # example config
├── FEATURES.md                      # this file
└── src/
    └── margoctl/
        ├── __init__.py
        ├── main.py                  # Typer app + command registration only
        ├── config.py                # dynaconf Settings (cross-cutting)
        │
        ├── domain/                  # pure logic — zero I/O, zero framework imports
        │   ├── tags.py              # semver validation
        │   ├── metadata.py          # publish_metadata.json dataclasses + parser
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
        │   ├── credentials.py       # ~/.config/margoctl/credentials.toml R/W
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

- All versions default to values in `publish_metadata.json` (read from CWD)
- CLI `--version` sets `app` version; individual component versions can be overridden
- Tag format functions are pure: `f"{version}-compose"`, `f"{version}-quadlet"`, etc.

### OCI operations (oras-py)

All OCI push/pull/fetch/login/logout go through `oras.client.OrasClient`. No subprocess
calls to the ORAS CLI binary. Credential expiry check runs before every registry
operation (push, pull, fetch). Rich `Progress` for long operations.

### Semver validation

Every tag value provided by the user (via flag, config, or `publish_metadata.json`) is
validated against the SemVer regex before any operation proceeds. Reject immediately
with a clear error. The tool does not construct tags with suffixes — the caller owns
the tag string entirely.

### Error handling

- Missing `publish_metadata.json` → clear error with instructions
- Invalid SemVer tag → reject immediately before any build/push step
- Credentials expired or near-expiry → warn or hard-fail with `margoctl login` hint
- ECR auto-refresh failure → clear error, do not proceed
- oras-py push/pull failure → surface exception message, exit 1
- Validation errors → rich table, exit 1

### Variant discovery

For `build --type compose --variant all`: scan `compose/` directory,
treat any subdirectory with a `compose.yaml` as a variant. Same for quadlet
(subdirs with `.container` files). Or explicit `--variant` list.

### `.rsyncignore`

If present in source dir, pass `--exclude-from=<path>` to rsync. Handles
symlinks with `-L` flag (already in existing tasks).

### Config file example (`margoctl.toml`)

```toml
registry = "public.ecr.aws"
repository = "org/myapp"
build_dir = ".dist"
run_dir = ".run"
```

### `margoctl login`

Authenticate with an OCI registry and persist credentials.

```
margoctl login [--registry REG] [--username USER] [--password-stdin]
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
Persist the expiry timestamp to `~/.config/margoctl/credentials.toml`:

```toml
[registries."public.ecr.aws"]
expires_at = "2026-06-26T23:00:00Z"
```

Every command that calls the registry checks this file first. If `now >= expires_at - 5min`,
print a warning and optionally auto-refresh if `--ecr` credentials are configured.

---

### `margoctl logout`

Remove stored credentials for a registry.

```
margoctl logout [--registry REG]
```

```python
client.logout(hostname=registry)
```

Also removes the expiry entry from `~/.config/margoctl/credentials.toml`.

---

### Credential Expiry — Design

**Problem:** ORAS (and oras-py) silently fail or give opaque errors when credentials
expire (ECR: 12h TTL). The caller has no signal until a push/pull fails mid-operation.

**Solution — proactive expiry check before any registry operation:**

```python
def check_credentials(registry: str) -> None:
    expiry = load_expiry(registry)  # from ~/.config/margoctl/credentials.toml
    if expiry is None:
        return  # no expiry tracked, proceed
    remaining = expiry - datetime.now(UTC)
    if remaining <= timedelta(0):
        raise CredentialsExpiredError(f"Credentials for {registry} expired. Run: margoctl login")
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
