# Sprint 13 — `margot install` (Quadlet)

**Status:** design settled (quadlet-only, three steps) — awaiting Gate 1 (branch/worktree split)
**Type:** feature
**Owner:** python-dev (docs: docs-writer)
**Release:** planned for `release/X.Y.Z` (TBD, after Sprints 11 and 12)

---

## 1. Goal

`margot install` installs **one deployment profile of type `quadlet`** of a Margo application on the
machine margot runs on (the local host plays the role of the Margo device; rootless Podman +
systemd user session is the reference environment), from any of three sources:

1. a **margot project** that has been built (`margot build`) — local, from the build directory;
2. a **static folder** — a bare `app.yaml` with its component archives next to it, typically the
   output of `margot pull --recursive`, **not** adopted by `margot migrate`;
3. a **remote artifact** in an OCI registry — including artifacts **not produced by margot**.

Delivered in three steps, each complete, tested and reviewable on its own:

- **Step 1 — files.** The quadlet files of every component are placed in
  `~/.config/containers/systemd/<application-id>/` and systemd re-reads them (`daemon-reload`).
  `install` **never starts** anything: it prints the `systemctl --user start …` commands.
- **Step 2 — parameters.** The application's `parameters` are applied as **systemd unit
  environment variables**, written in Quadlet drop-in files next to the units
  (`<unit>.<suffix>.d/50-margot-parameters.conf`, section `[Service]`). The unit files consume them
  with systemd's own variable expansion (`${NAME}` in `Exec=`, `PublishPort=`, `Volume=`,
  `Environment=`, …). Values come from descriptor defaults and `--set NAME=VALUE`.
- **Step 3 — final checks.** Guards that make the install safe on a real host: unit-name collision
  detection across the whole Quadlet search path, Quadlet-generator dry-run validation of the
  staged files before the host is touched, and verification that systemd knows every expected
  service after the reload.

Compose and Helm are **not** part of this sprint (compose apply is the next install sprint; Helm
stays an accepted limitation). Principle (owner): *simple, but 100 % working.* Anything that cannot
be done reliably is refused with a clear message; nothing is attempted "best effort".

Target workflow:

```text
margot build -t all && margot install                       # project: install what was just built
margot pull <uri> --recursive && margot install             # static folder
margot install <uri>                                        # remote
margot install <uri> --set nginxPort=9090                   # Step 2
margot install --dry-run                                    # show the plan, change nothing
systemctl --user start nginx.service                        # printed by install; run by the user
```

---

## 2. Context

- margot builds, publishes, pulls, validates and describes Margo applications but cannot run
  them. `install` closes that gap for quadlet, the runtime the owner uses in production-like setups.
- A deployment profile has exactly one `type` (`helm`, `compose`, `quadlet`) and an `id` unique
  within the application description. The profile id is the only selector; there is no `--type`.
  The **application id** is the descriptor's top-level `id` (e.g. `com-example-nginx`); it names
  the install directory.
- Components are located by `properties.repository` + `properties.revision` (OCI). The Margo spec
  also allows `packageLocation` (+ `keyLocation`) for compose; out of scope (§3.1).
- **Why non-margot artifacts matter (owner):** the point of `install` is to install *Margo
  artifacts*, whoever produced them. Everything on the remote path relies on the Margo spec and
  OCI metadata — descriptor layer by `mediaType` (Sprint 11), component type by `artifactType`,
  payload by file content — never on margot-only conventions (`margo.yaml`, `<name>-<version>.tgz`
  file names, tag suffixes).
- `pull --recursive` writes components to `<outdir>/<component name>/<layer file>` and
  deduplicates by `(repository, revision)`, keeping the **first** component name. A second
  component with another name but the same artifact has no folder: `install` gives an actionable
  error, not a guess.
- `build` writes `<build-dir>/<tag>/margo/app.yaml` for the margo artifact and
  `<build-dir>/<tag>/<name>-<tag>.tgz` for each compose/quadlet component, where `<tag>` is the
  version with `+` replaced by `_`. A flat compose and a flat quadlet at the same version share
  the same path (existing property, shared with `push`) — `install` detects it by content (§3.4).
- **The Margo spec does not define quadlet.** Its `parameters[].targets[].pointer` is defined only
  for Helm (a values path) and Compose (an environment-variable name). This sprint **defines the
  quadlet meaning of `pointer`** (§3.9): the name of an **environment variable of the systemd
  unit** of the target component. The repo's own `docs/examples/full.md` already targets quadlet
  components with `pointer: NGINX_PORT`, which fits.
- **Quadlet / systemd facts already verified** on this machine (Podman 5.8.2, systemd 258) with
  `/usr/libexec/podman/quadlet -dryrun -user` and `QUADLET_UNIT_DIRS` on a temp tree, and with
  `systemd-run --user`. Spikes S1/S2 re-confirm them on the real session; they are not to be
  re-derived from scratch:
  - A unit placed in a sub-directory is found; its `foo.container.d/*.conf` drop-ins **beside it**
    (same sub-directory) are merged into the source file before the service is generated.
  - A drop-in `[Service] Environment=NAME=value` is copied into the generated service's `[Service]`
    section untouched (`[Service]` and `[Install]` pass through Quadlet).
  - Quadlet does **not** touch `${VAR}`: in `Exec=`, `PublishPort=`, `Volume=`, `Label=`,
    `Environment=` and `Image=` it appears verbatim in the generated `ExecStart=`
    (`… --publish ${PORT}:80 … nginx:${TAG} nginx … ${GREETING}`), so **systemd** expands it
    from the unit's `Environment=` at start. A bare `Environment=NAME` in `[Container]` is accepted
    and becomes `--env NAME` (podman then takes the value from its own environment, i.e. the
    unit's — S2 confirms this passes the value into the container).
  - systemd expansion: `${X}` is substituted as **one** argument even with spaces; `$X` is
    word-split; an undefined variable expands to the empty string; a substituted value is not
    expanded again (`$` inside a value is safe). An unquoted value with spaces in `Environment=` is
    an "Invalid environment block", so values are always written double-quoted. `%` is a unit-file
    specifier and must be written `%%` in a unit file (S2 verifies on a real drop-in, the
    `systemd-run -p` test bypasses specifier parsing).
  - Service names come from the **file name**, not the directory: `web.container` → `web.service`,
    `data.volume` → `data-volume.service`. Two applications shipping a same-named unit collide;
    with two copies in one search tree only one service is generated, silently (§3.10).
  - Quadlet search path for the user: `$XDG_RUNTIME_DIR/containers/systemd`,
    `$XDG_CONFIG_HOME/containers/systemd` (default `~/.config/containers/systemd`),
    `/etc/containers/systemd/users/$UID`, `/etc/containers/systemd/users`,
    `/usr/share/containers/systemd/users/$UID`, `/usr/share/containers/systemd/users`. Sub-directories
    are scanned recursively. Source suffixes per the docs: `.container .volume .network .build .pod
    .kube .artifact` (and `.image`); S1 confirms against the installed Podman.
- Layering and rules: `commands/` → `services/` → `domain/` + `infra/`; `domain/` is pure; all
  terminal output through `margot.console`; rich values per `rich-rendering.md`; selective imports;
  exit-code taxonomy in `code-conventions.md`; TDD.
- `console.py` is the only module allowed to touch `sys.stdin/stdout/stderr`; interactive
  confirmation therefore lives there (§3.6).
- There is no `subprocess` use in `src/margot` today; this sprint introduces the first one (Sprint
  15 adds a second for helm). Check Ruff's `S603`/`S607` configuration before assuming they are quiet.

Dependencies (land first):

- **Sprint 11** — `mediaType`-based descriptor-layer lookup (remote path relies on it).
- **Sprint 12** — descriptor resolution without a project file (`<dir>/app.yaml`, then
  `<dir>/margo/app.yaml`; static only).
- Sprint 14 (project file rename and `migrate`) lands **after** this sprint and sweeps `install` (§3.12).
  Do not anticipate it here.

---

## 3. Authoritative Design

### 3.1 Scope

**In scope:** `margot install` for `quadlet` profiles from the three sources; profile selection;
safe staging; plan display, confirmation, `--dry-run`; placing the quadlet files and reloading
systemd (Step 1); parameters as unit environment through drop-ins (Step 2); collision detection,
generator pre-validation and post-reload verification (Step 3); an ownership marker; docs.

**Out of scope (non-goals — recorded in ROADMAP):**

- **Compose and Helm profiles** — refused with a clear message ("not supported yet" / "no cluster
  on the host"). Compose apply is the next install sprint.
- **Starting, enabling or stopping the workload.** `install` only prints the commands. There is no
  `--start` flag.
- **Components located by `packageLocation` / `keyLocation`** — refused, naming the component.
- **Validating `--set` values against the descriptor's schema** (`dataType`, `minLength`, …) —
  complex to set up; a later sprint. In this sprint values are strings.
- **Parameters other than unit environment variables** for quadlet, array data types, per-unit
  targeting inside a component, secret handling beyond file permissions (§3.9).
- **`uninstall`, `list`/`status`** — the marker (§3.8) is written now so they can follow.
- Installing a bare quadlet component by URI (no application, no profile).
- `--json` output; `--force`; `--type`; `--runtime`; `--version`; schema validation of the
  descriptor as a gate (run `margot verify` first — `install` prints that hint).
- Rollback after a partial failure (reported, not undone).
- Root / system-wide installs; `sudo` is never used or assumed.

### 3.2 Command

```text
margot install [URI] [--project-dir DIR] [--build-dir DIR] [--profile ID]
               [--set NAME=VALUE]...   # Step 2 only
               [--yes] [--dry-run]
```

| Argument / option | Meaning |
| --- | --- |
| `URI` (optional) | OCI reference of a **margo** artifact (`oci://` optional). Selects the remote source. |
| `--project-dir DIR` | Local source directory (default `.` when no `URI`). Mutually exclusive with `URI`. |
| `--build-dir DIR` | Build output directory for project mode (default `.dist`, as `build`/`push`). Rejected with `URI`; rejected (usage error) in static mode. |
| `--profile ID` | Deployment profile `id` to install. See §3.3. |
| `--set NAME=VALUE` | **Step 2.** Value (a string) for the descriptor parameter `NAME`; repeatable, last wins. See §3.9. |
| `--yes`, `-y` | Do not ask for confirmation. |
| `--dry-run` | Resolve, stage and validate, print the plan, change nothing on the host, exit 0. Never asks. |

Source detection — mirrors `describe`/`verify` (Sprints 9, 12); no mode flag:

| Situation | Source |
| --- | --- |
| `URI` given | remote |
| no `URI`; `<project-dir>/margo.yaml` present | project (built output) |
| no `URI`; no `margo.yaml`; descriptor found by Sprint 12 search order | static folder |
| otherwise | error listing the paths tried (exit 3) |

(The project file name is `margo.yaml` here; Sprint 14 renames it.) Usage errors → exit 2 before
any work: `URI` with `--project-dir`/`--build-dir`; `--build-dir` outside project mode (checked
once the source is known); a `--set` argument without `=`; no TTY and neither `--yes` nor `--dry-run`.

### 3.3 Profile selection and components

Pure functions in `domain/install.py`.

1. Installable = profile `type` == `quadlet`. `compose`, `helm` and any other type are not
   installable.
2. `--profile ID` given: must exist (error lists the available ids and their types); if it is not
   installable, error naming its type (compose: "not supported yet"; helm: "not supported").
   Not given: exactly one installable profile → selected (and announced); several → error listing
   the ids (exit 3, it depends on the descriptor); none → error. An application that ships both a
   compose and a quadlet profile therefore installs without `--profile`.
3. A selected profile must have at least one component. Every component needs a non-empty `name`
   and `properties.repository` + `properties.revision`. A component with `packageLocation` and no
   repository/revision is refused naming the component and the limitation. All components are
   checked **before** anything is staged, so one bad component fails the whole install up front.
4. Component names become path segments (staging): each goes through
   `domain/layers.py::sanitize_filename`; a rejected name fails the install (exit 3). The
   application `id` is sanitised the same way for its install directory.
5. Every unique `(repository, revision)` is staged once; two components sharing one artifact are
   both installed from it.

### 3.4 Staging — everything is resolved before the host is touched

For every selected component, obtain a **tar archive** and extract it into a staging directory
(`tempfile.TemporaryDirectory`, removed in a `finally`). Nothing outside staging is written until
the plan has been shown and confirmed.

| Source | Descriptor | Archive for component *c* |
| --- | --- | --- |
| project | `<build-dir>/<version>/margo/app.yaml`, `version` from `margo.yaml` with `+`→`_`. Missing → error "run `margot build -t all`" (exit 3) | `<build-dir>/<tag>/<meta.name>-<tag>.tgz`, `tag` = `c.revision` with `+`→`_`. Missing → listed in one error ("component(s) not built, or not built by this project — use `margot install <uri>` for external components") |
| static | the file found by Sprint 12's search; a `.jinja` is the existing actionable error | the single regular file in `<dir of app.yaml>/<sanitised c.name>/`, which must be a tar archive. Missing folder → error naming the expected path and suggesting `margot pull <uri> --recursive`; zero or several files → error |
| remote | `resolve_remote_descriptor(uri)` (shared with `describe`/`verify`; rejects non-margo artifacts; temp dir cleaned in `finally`) | `prepare_oci_retrieval(f"{repository}:{revision}")`, check `package_type` is `quadlet` (mismatch → error, exit 3), `pull_prepared_context` into a per-component staging folder; then the same single-archive rule |

Project mode never falls back to the registry: a built project installs exactly what was built.
Credential-expiry checks and registry errors come from the existing code (exit 4).

**Safe extraction** (`infra/filesystem.py`): `tarfile` with `filter="data"`, into a fresh empty
directory; if the archive has exactly one top-level directory it is stripped (margot's layout; an
archive from other tooling may or may not have it). Hostile archives (absolute paths, `..`,
escaping links, devices) fail that component → the install fails (exit 3).

**Payload validation** (pure, on the extracted file list; content-based, never by archive name):
the payload must contain **at least one file with a quadlet suffix at its root**. Else error (exit
3); if the payload contains a compose file, say so (this catches the flat compose/quadlet path
collision).

**Merge validation** (pure, across the selected components): the components are installed into
**one directory** (§3.7), so two components may not ship the same relative path. A clash names both
components and the path (exit 3). The list of quadlet units (file name → generated service name)
is computed here once and reused by the plan, the marker and Step 3.

### 3.5 Plan, confirmation, dry-run

`services/install.py` exposes two phases so the command can interact in between:

1. `prepare_install(...) -> PreparedInstall` — resolves the source, selects the profile, stages,
   validates and builds the plan. `PreparedInstall` owns the staging temp directory; **the caller
   cleans it in a `finally`** (same contract as `ResolvedRemoteDescriptor`).
2. `apply_install(prepared) -> InstallResult` — performs the host actions (§3.7) and writes the
   marker (§3.8).

The plan is a pure display dataclass built in `domain/install.py` (no `rich`, no `console`):
application id · name · version, profile id · type, source (kind + URI or path), target
directory, and per component: name, artifact reference (or built path), archive `sha256`, the
files that will be written, and the services they generate. Step 2 adds the parameter table
(§3.9). `commands/install.py` renders it (Panel/Tree/Table per `rich-rendering.md`: data in `Text`,
` · ` composition, no truncation, shallow tree, scalars literal) and prints, once, the hint
*"descriptor not schema-validated by install; run `margot verify` first"*.

Then: `--dry-run` → stop, exit 0. Otherwise, unless `--yes`, ask `Install N component(s) on this
host? [y/N]` through `console.confirm()`; **declined → "Aborted: nothing was installed", exit 1**
(documented in `docs/exit-codes.md`). No TTY without `--yes`/`--dry-run` → exit 2.

Declared parameters that are not applied (Step 1: all of them; Step 2: those without a value):
`domain/install.py::unapplied_parameters(doc, component_names)` returns their names; one
`console.warning` lists them.

### 3.6 `console.confirm`

Added to `src/margot/console.py` (the sole owner of stdin/stdout/stderr access): prints the
question to stderr, reads one line through the existing stdin helper, accepts `y`/`yes`
(case-insensitive), everything else (including EOF) is "no". Plus an `is_interactive()` helper for
the TTY check. Unit-tested with swapped streams like the existing console tests.

### 3.7 Step 1 — placing the files

Runs only after confirmation. Target (XDG-aware, rootless):

```text
$XDG_CONFIG_HOME/containers/systemd/<application-id>/      # default ~/.config/containers/systemd/
├── .margot-install.json          # ownership marker (§3.8)
├── nginx.container               # unit files of ALL selected components, flat merge
├── nginx.container.d/            # Step 2: parameter drop-ins, beside their unit
│   └── 50-margot-parameters.conf
└── conf/nginx.conf               # any other payload file, relative paths preserved
```

Why one flat directory per application (owner's layout): quadlet service names are global, so a
component level adds nothing; relative paths inside units (`Volume=./conf:/etc/x`) resolve against
the unit file and keep working.

**Pre-checks** (all before any file is written):

1. **Systemd user session usable** — `systemctl --user show-environment` succeeds. Else exit 1
   mentioning the user session / `XDG_RUNTIME_DIR` (nothing applied).
2. **Ownership of the application directory** (exit 3). `<application-id>/` absent → fresh install.
   Present **with** a marker → it is ours: same profile id → upgrade, **different profile id →
   refused** (names the recorded profile and path; no `uninstall` yet). Present **without** a
   marker → refused ("not installed by margot"; margot never adopts or overwrites a directory it
   did not create).

**Write.** (a) create the directory and write the marker with `state: "installing"` and the
intended file list; (b) write each payload file (temp file + `replace`; modes preserved but never
group/world-writable); (c) on upgrade, delete files that the **previous marker** lists and the new
payload does not (user-added files — e.g. a hand-written `90-local.conf` drop-in — are never
listed, so never touched), then prune empty directories; (d) update the marker to
`state: "installed"`. Re-running after a failure is safe at every point.

**Reload.** `systemctl --user daemon-reload`. Failure → exit 1 with trimmed stderr and what was
written.

**Result (stdout).** The installed directory, the generated service names, and the next steps —
margot prints the commands and does not run them:

```text
systemctl --user start nginx.service
systemctl --user status nginx.service
```

The hint also mentions: a first start may pull images and exceed systemd's 90 s default
(`TimeoutStartSec`); units with `[Install] WantedBy=default.target` are enabled by the generator
itself and start at the next login/boot (lingering for boot-time start) — said only if it can be
read from the unit file. In Step 2, if parameters were applied, the hint states that the values are
visible through `systemctl --user show` / `cat`.

Commands are argument lists, `shell=False`, captured output (text), never `check=True`,
`console.debug` per call (infra rule). The wrapper lives in `infra/systemd.py`; all of it is
unit-tested with a mocked `run`.

**Failure behaviour.** The error states what was written, which step failed, the trimmed stderr,
and that nothing was rolled back. Re-running `install` after fixing the cause is safe.

### 3.8 Ownership marker

`<application-id>/.margot-install.json`, written by `infra/install_store.py` (stdlib `json`, atomic
via temp file + `replace`, `console.debug` per I/O). Content (`domain/install.py::InstallRecord`,
pure (de)serialisation to a dict):

```text
schema: 1
state                  installing | installed
appId, appName, appVersion
profileId
installedAt            UTC, ISO 8601
source                 { kind: project|static|remote, uri | path }
components[]           { name, repository?, revision, archiveSha256,
                         files[] (relative to the app directory, drop-ins included) }
services[]             generated service names
parameters[]           Step 2: names of the parameters applied (never their values)
```

Quadlet ignores files without a unit suffix, and the marker is inside the application directory so
that ownership is self-evident, deleting the directory deletes the record, and a future
`uninstall` is "read marker, delete listed files, remove directory, `daemon-reload`". Parameter
*values* are not copied into the marker.

### 3.9 Step 2 — parameters as unit environment variables

**Meaning of `pointer` for quadlet (defined here):** the name of an **environment variable of the
systemd unit(s)** of the target component. It must match `[A-Za-z_][A-Za-z0-9_]*`; anything else
is refused naming the parameter, pointer and component (exit 3). This mirrors the spec's compose
definition (an environment-variable name) while giving the unit author the full power of systemd
expansion.

**How a unit consumes a parameter (documented for quadlet authors).** margot sets
`NAME` in the unit's environment; the unit file decides where it goes:

```ini
[Container]
Image=docker.io/library/nginx:1.27.0
PublishPort=${NGINX_PORT}:80          # systemd expands it in the generated ExecStart
Environment=NGINX_PORT                # pass the unit's value into the container (S2 confirms)
Exec=nginx -g "daemon off;" --x ${GREETING}
```

Use `${NAME}` (braces): it is substituted as a single argument; `$NAME` is word-split by systemd.
A parameter that no unit file references has no effect.

**Which parameters.** A parameter is *applicable* when at least one of its `targets[].components`
names a component of the selected profile; other targets are ignored (they belong to other
profiles). Two applicable parameters mapping to the same pointer on the same component are a
conflict (exit 3).

**Which units.** Every quadlet unit file contributed by the target component (any suffix: the
drop-in is a `[Service]` section, which every generated service has). Each unit of the component
receives all of that component's variables (documented; per-unit targeting is a follow-up).

**Values (strings only; no schema validation in this sprint).**

| Source | Rule |
| --- | --- |
| `--set NAME=VALUE` | wins over the descriptor; `NAME` must be an applicable parameter (else exit 3, listing the applicable names); the value is used as given |
| descriptor `value` | used when no `--set`; rendered as: string as is, integer/double decimal, boolean `true`/`false` |
| neither | not applied, listed by `unapplied_parameters` |
| array data types (descriptor value is a list) | refused for quadlet when applicable (exit 3, names the parameter) — no invented separator |

**Drop-in file.** For each unit `U.<suffix>` of the component:
`U.<suffix>.d/50-margot-parameters.conf`, mode `0600`:

```text
# Managed by margot - regenerated on every install.
# Add your own overrides in a differently named file (e.g. 90-local.conf).
[Service]
Environment="NAME=<encoded value>"
```

One `Environment=` line per variable, sorted by name (deterministic output). The encoder
(`domain/install_parameters.py::encode_environment`, pure) produces the double-quoted assignment so
that systemd stores the value **unchanged**: it escapes `\` and `"`, doubles `%` (unit-file
specifier), and always quotes. Values containing a newline, CR or NUL are refused (exit 3). Exact
rules and the vector table come from spike S2 and are verified end to end on the real host.

On upgrade, a previously written parameters drop-in that the new run no longer produces is deleted
(it is listed in the previous marker). Drop-ins margot did not write are never touched. A
later-sorting user drop-in overrides margot's — by design (`systemctl --user edit` also works).

**Plan and storage.** The plan shows a table: parameter · value · source (`descriptor` / `--set`)
· variable · units. Values appear in clear text on screen. The drop-in is `0600`, but the value is
visible through `systemctl --user show` and, if the unit passes it on, `podman inspect`; documented
as a limitation (no secret store in this version).

### 3.10 Step 3 — final checks

Three guards, all in `services/install.py` with pure helpers in `domain/install.py`. They are
built last so they can be exercised against the complete flow (units + drop-ins).

1. **Unit-name collision (hard error, exit 3).** Before any file is written: for every unit file
   to install, no file with the same name exists anywhere in the user Quadlet search path (the six
   roots in §2, recursively) **outside this application's own directory** — this includes sibling
   applications installed by margot and hand-written units. The error names both paths. margot never
   renames a unit (that would break `Network=foo.network`-style references) and never shadows
   someone else's. The check also runs in `--dry-run` so the plan reports it.
2. **Generator dry-run validation (host untouched, exit 3).** Run `quadlet -dryrun -user` with
   `QUADLET_UNIT_DIRS=<staging merge tree, drop-ins included>`. A non-zero exit or error output
   fails the install **before** the host is touched, with the trimmed generator output. Binary
   lookup (`/usr/libexec/podman/quadlet`, `/usr/lib/podman/quadlet`, `$PATH`; S1 fixes it): not
   found → one `console.warning`, the install continues (guard 3 still applies).
3. **Post-reload verification (exit 1).** After `daemon-reload`, each expected service (pure
   derivation from the unit list, table from S1) must be known to systemd
   (`systemctl --user cat <service>` exits 0). A missing service means the generator rejected a
   file: error with the service name, the unit file, and the hint to run the generator in dry-run
   mode or `journalctl --user -b -t quadlet-generator`.

### 3.11 Error cases

| Case | Code | Behaviour |
| --- | --- | --- |
| `URI` with `--project-dir`/`--build-dir`; `--build-dir` in static mode; `--set` without `=` | 2 | usage error naming the options |
| no TTY, no `--yes`/`--dry-run` | 2 | usage error |
| no descriptor / no built output / unreadable YAML | 3 | names the paths tried; suggests `margot build`, `margot pull -r` |
| unknown / ambiguous / compose / helm / non-installable profile | 3 | lists available ids and types |
| component without `repository`+`revision` (incl. `packageLocation`) | 3 | names the component; limitation message |
| unsafe component name / application id | 3 | names the offending value (rendered as data, `rich-rendering.md`) |
| archive missing / not a tar / no quadlet unit / hostile archive | 3 | names the component and the reason |
| two components ship the same path | 3 | names both components and the path |
| remote artifact is not a margo artifact | 3 | existing `resolve_remote_descriptor` message |
| application directory exists without marker; recorded profile differs | 3 | names the path / recorded profile |
| Step 2: unknown `--set` name; bad pointer; same pointer twice on a component; array value; newline/NUL in value | 3 | names the parameter (and component) |
| Step 3: unit name already present elsewhere in the search path; generator dry-run fails | 3 | names both files / trimmed generator output |
| registry / credentials failure | 4 | existing handling |
| `systemctl --user` unusable; `daemon-reload` fails; expected service missing after reload | 1 | trimmed stderr; what was written |
| user declines | 1 | "Aborted: nothing was installed" |

### 3.12 Interaction with the project file rename (Sprint 14)

`install` reads the project file through exactly **one** call site (`load_margo_yaml`) and mentions
the file name in few messages, so Sprint 14's sweep is small; Sprint 14's checklist already carries
the line. `install` does not use `pull --recursive`, so it does not depend on Sprint 14's
component-name sanitisation (it sanitises by itself, §3.3).

### 3.13 Layering summary

| Layer | New code |
| --- | --- |
| `commands/install.py` | Typer parsing, usage checks, plan rendering, confirmation, `try/finally` cleanup, exit codes; registered in `main.py` |
| `services/install.py` | `prepare_install`, `apply_install`; source resolution (reusing `resolve_remote_descriptor`, `prepare_oci_retrieval`, `pull_prepared_context`, Sprint 12 resolution); Step 3 guards; `console.info` per step |
| `domain/install.py` | profile selection, component specs, payload and merge validation, unit → service derivation, collision detection (pure, over path lists), `unapplied_parameters`, plan and record dataclasses |
| `domain/install_parameters.py` (Step 2) | applicable parameters, value resolution, drop-in text rendering, `encode_environment` — pure |
| `infra/systemd.py` | `systemctl --user` calls, quadlet generator lookup and dry-run |
| `infra/install_store.py` | marker read/write, XDG paths, search-path listing, file placement and stale-file removal |
| `infra/filesystem.py` | safe archive extraction (top-level strip), `sha256` |
| `console.py` | `confirm`, `is_interactive` |

---

## 4. Checkable Steps

TDD throughout: tests are written before the code they cover, and a failing test is the expected
state until the implementation lands. One branch (`feat/install`), sequential tasks, each task one
or more conventional commits. **The dev agent stops at Checkpoint A (after Step 1) and Checkpoint B
(after Step 2) and reports to the planner; the next step starts only after the owner has reviewed.**

### Spikes (first; results written into §2 / §3.7 / §3.9 / §3.10 of this file and reported to the planner)

- [ ] **S1 — quadlet layout on the real rootless session.** `podman --version`. Place a small
  multi-unit fixture (container + network + volume, and a pod variant) under
  `…/containers/systemd/<app>/`, `systemctl --user daemon-reload`, and determine: generated service
  name per unit type (table for §3.7/§3.10); suffix list as accepted by this Podman (incl. `.image`,
  `.artifact`); which services need an explicit start vs are pulled in as dependencies (this decides
  the "next steps" lines install prints); which search directories are really scanned and what
  happens with a duplicate unit name across them (first wins? error? silent?); behaviour of
  `[Install] WantedBy=default.target`; the exit code and output of `quadlet -dryrun -user` on a valid
  and on an invalid file, and where the binary lives (also check `/usr/lib/podman/quadlet`);
  decision on `podman quadlet install` (Podman ≥ 5.6) versus manual copy — **default is the manual
  copy** because drop-ins and the `<application-id>` layout are required; record the evidence.
  Also inspect what `podman quadlet install` leaves in the Quadlet directory to track an installed
  application (observed on 5.8.2: files copied flat, plus a hidden `.<dir>.app` marker; confirm its
  content), whether `podman quadlet list` / `rm` misbehave on margot's per-application layout, and
  record whether margot's `.margot-install.json` should also be recognisable by Podman or just
  coexist with it.
- [ ] **S2 — parameters as unit environment (needed before Step 2 code).** On real Quadlet units
  with a `[Service]` drop-in, establish and record: (a) the encoding of `Environment="NAME=…"` so
  the value is stored by systemd byte-for-byte (check `systemctl --user show -p Environment <svc>`
  after `daemon-reload`) — inputs: empty, leading/trailing spaces, inner spaces, `"`, `'`, `\`, `%`,
  `%%`, `$VAR`, `${VAR}`, `$$`, `#`, `;`, `=`, tab, non-ASCII, 1 KiB; (b) that `${NAME}` in
  `PublishPort=`, `Exec=`, `Volume=`, `Label=`, `Environment=X=${NAME}` and `Image=` is expanded by
  systemd in the running container's command line (`podman inspect`, `podman ps`), for a value with
  spaces too; (c) that a bare `Environment=NAME` in `[Container]` delivers the unit's value into
  the container (`podman exec … printenv NAME`); (d) what happens when the variable is **not** set
  (empty expansion — does the start fail in a readable way?). Deliver: the encoding rules and the
  table of vectors (input → drop-in line → value seen) that becomes the unit-test fixture, and the
  exact snippet recommended to quadlet authors in the docs.

### Step 1 — files

- [ ] Tests first, then `domain/install.py`: profile selection (all rows of §3.3), component
  validation (incl. `packageLocation`), name sanitisation, payload validation (quadlet; compose
  collision message), merge validation (same path in two components), unit → service derivation
  (from S1), `unapplied_parameters`, plan and record dataclasses and the record (de)serialisation
  round trip.
- [ ] `infra/filesystem.py`: safe extraction with top-level strip (hostile-archive tests: absolute,
  `..`, symlink escape, device), `sha256`.
- [ ] `infra/systemd.py`: `systemctl --user` argv construction and error mapping (mocked `run`).
- [ ] `infra/install_store.py`: XDG path resolution (`XDG_CONFIG_HOME` set and unset), marker atomic
  write/read (tolerant of a missing file), file placement with stale-file removal driven by the
  previous marker.
- [ ] `console.confirm` / `is_interactive` + tests.
- [ ] `services/install.py::prepare_install`: **project** mode (built fixture in `tmp_path`: missing
  build dir, missing component archive, compose payload in a quadlet profile, success); **static**
  mode (`pull -r`-shaped fixture: missing folder, several files, non-tar, valid; Sprint 12
  `.jinja` error passes through; component deduplicated by `pull -r`); **remote** mode with the
  existing fake `OrasClient` boundary (non-margo artifact rejected, component type mismatch,
  credential expiry → exit 4 path, success; temp directories removed in all paths); a
  non-margot-shaped fixture (archive without a top-level directory, different file names,
  descriptor layer found by `mediaType`) through the remote path.
- [ ] `apply_install` with the mocked systemd wrapper and a `tmp_path` XDG root: files at the
  expected paths with preserved relative layout; marker `installing` → `installed`; ownership
  refusals (no marker; other profile); upgrade removes stale files listed by the previous marker and
  keeps unlisted user files; `daemon-reload` argv; `systemctl --user` unusable → nothing written;
  **no `start`/`enable` call is ever made**; **`--dry-run` writes nothing and calls nothing**
  (asserted by a test).
- [ ] `commands/install.py`: usage errors (exit 2), exit-code table of §3.11 (test names and
  docstrings carry the asserted number), plan rendering (values with `[`…`]` such as
  `array[string]` or `[Container]` render intact), printed next-step commands, `--dry-run` does not
  ask, `--yes`, decline → 1, non-TTY → 2, staging cleanup on every path; register in `main.py`.
  E2E (`CliRunner`, mocked systemd wrapper): project, static, remote → install; `--dry-run` for
  each; `--help`.

### Checkpoint A — Step 1 real-host verification and review (required — not CI)

- [ ] On the dev machine (Fedora, rootless Podman) with a quadlet fixture built from
  `docs/examples/basic-quadlet.md`: `margot install --dry-run`; `margot install --yes`; verify
  `~/.config/containers/systemd/<application-id>/` content and marker, `systemctl --user list-unit-files`
  shows the generated service, run the printed `systemctl --user start` and confirm with `podman ps`;
  re-install (idempotent); manual cleanup. Paste commands and outcomes in the report. Remote path
  against a local registry if one is available, otherwise state it was verified with the faked
  registry only.
- [ ] `make check` passes. **Stop and report to the planner for owner review before Step 2.**

### Step 2 — parameters

- [ ] Tests first, then `domain/install_parameters.py`: applicable-parameter selection by
  component, conflicts (same pointer twice), pointer validity, value resolution (`--set` over
  descriptor value; none → unapplied; bool/number rendering), array refusal, drop-in text rendering
  (deterministic order, header, `[Service]`), `encode_environment` against **every vector from S2**,
  newline/CR/NUL refusal.
- [ ] `--set` option on `commands/install.py` (usage error without `=`; repeated names: last wins,
  announced; unknown name → exit 3); parameter table in the plan (values containing `[`…`]` render
  intact).
- [ ] `apply_install`: a drop-in written beside **every** unit of the target component, mode
  `0600`; stale margot drop-ins removed on upgrade; user-named drop-ins untouched; marker
  `parameters[]` holds names only and `files[]` lists the drop-ins.
- [ ] Update `docs/examples/full.md` / `docs/templating.md` quadlet samples so the unit files
  reference `${NGINX_PORT}` (docs-writer, with the install page).

### Checkpoint B — Step 2 real-host verification and review (required — not CI)

- [ ] Install with defaults and with `--set` (a value with spaces, `%`, `$` and `"`); start the
  unit with the printed command; confirm with
  `systemctl --user show -p Environment`, `podman inspect` / `podman exec … printenv` and
  `podman ps` (published port) that the unit and the container see each value exactly;
  `systemctl --user cat` shows the merged unit; a hand-written `90-local.conf` overrides and
  survives a re-install. Paste outcomes. `make check` passes. **Stop and report.**

### Step 3 — final checks

- [ ] Tests first, then the pure helpers (search-path listing, collision detection over path
  lists) and the guards: collision with a hand-written unit, with a sibling margot application and
  inside the application's own directory (allowed); the collision error appears in `--dry-run`;
  generator dry-run (found → pass, found → fail with exit 3 and nothing written, not found →
  warning and continue; drop-ins are part of the tree it validates); post-reload verification
  (service known → ok; missing → exit 1 with the hint). All with the mocked wrapper.
- [ ] Real-host verification: a second application shipping an existing unit name is refused with
  both paths named; an invalid unit file is caught by the dry-run before anything is written; the
  happy path of Steps 1–2 still passes end to end.

### Docs (docs-writer) and close-out

- [ ] `docs/commands/install.md` (synopsis, flag table, three sources, profile selection, what is
  written where, the marker fields, parameters and the quadlet meaning of `pointer` with the
  consumption snippet from S2, how to run the workload (`systemctl --user start`, lingering for
  boot-time start), exit codes, examples, **limitations**: compose/helm, `packageLocation`,
  parameters = unit environment variables only, no schema validation of `--set`, all units of a
  component get all its variables, clear-text values, no `start`/`enable`, no `uninstall`, no
  rollback); `mkdocs.yml` nav entry; `docs/exit-codes.md` (install rows incl. "declined → 1");
  `docs/concepts.md` pointer; README command table; `.kiro/steering/product.md` command list.
  `make docs-check` passes.
- [ ] ROADMAP: this sprint to Completed (with release link), follow-ups in §7 confirmed present.
- [ ] Sprint file deleted in `chore(sprint): close out sprint-13 — margot install`.

---

## 5. Definition of Done

- [ ] All checkable steps completed, spike results recorded in this file.
- [ ] `make check` passes (lint + unit + integration, coverage threshold).
- [ ] Real-host verification done and reported at Checkpoints A and B and for Step 3.
- [ ] `install` never starts, enables or stops a service; no `--start`, schema-validation gate,
  `--force`, `--type`, `--runtime` or `--version` surface exists.
- [ ] Nothing is written outside staging before confirmation; `--dry-run` leaves the host and the
  config directories untouched (asserted by a test).
- [ ] margot never writes into, removes from, or adopts a directory without its marker, and never
  installs a unit whose name already exists elsewhere in the Quadlet search path.
- [ ] Docs updated; `make docs-check` passes.
- [ ] No bare TODOs (`# TODO(kiro): …` only, each with a ROADMAP entry).
- [ ] Each task committed as one or more commits on `feat/install` — no bulk commit.
- [ ] Handed back for review (Gate 2). The agent does not push, open PRs, or manage worktrees.

---

## 6. Close-out Note

```text
(filled in after merge)
```

---

## 7. Decisions

Settled (owner):

1. Install target is the local host; **quadlet only** in this sprint; compose next, helm later.
2. No `--type` (a profile has one type); no `--force`; no descriptor schema gate.
3. Sprint order: this sprint is 13; the project file rename/`migrate` sprint is 14, helm sprints 15–16.
4. `packageLocation` components are an accepted limitation.
5. Step 1 installs the files under `~/.config/containers/systemd/<application-id>/`; Step 2 adds
   parameters through systemd/Quadlet drop-ins; Step 3 is the final checks.
6. **`pointer` = systemd unit environment variable** (not only container environment), so quadlet
   authors can use systemd variable expansion in `Exec=`, `PublishPort=`, etc.
7. **`install` does not start anything**; it prints the start commands. No `--start` flag.
8. **`--set` values are not validated against the schema** in this sprint (future work).
9. **Unit-name collisions are a hard error** (no renaming, no override), built as part of Step 3.
10. **The ownership marker lives inside the application directory**
    (`<application-id>/.margot-install.json`, §3.8). Podman does the same in spirit:
    `podman quadlet install <dir>` (5.8.2, checked) copies the files flat into
    `~/.config/containers/systemd/` and records the application as a hidden `.<dir>.app` file in
    that directory. margot differs on purpose: one directory per application (owner's layout), so
    the marker sits inside it. `podman quadlet list` shows margot-installed units without an
    application name; that is accepted.

Open point for the owner (no action needed unless it is wrong): the generator dry-run and the
post-reload verification are grouped in Step 3 with the collision check (§3.10), keeping Step 1 to
"place the files".

Follow-ups to record in ROADMAP at close-out: compose apply (next install sprint) and compose
parameters (environment); `--set` validation against the descriptor schema; `uninstall` / `list` /
`status`; per-unit parameter targeting; array data types and a secret mechanism for parameters;
`immutable` enforcement on upgrade; `--json`; rollback; `packageLocation`; helm.

---

## References

- [sprint-workflow skill](../skills/sprint-workflow/SKILL.md)
- [ROADMAP.md](../../ROADMAP.md)
- Sprint 11 (shipped in 0.11.0), [sprint-12.md](./sprint-12.md) — prerequisites.
- [sprint-14.md](./sprint-14.md) — project file rename, sweeps `install`.
- Steering: `code-conventions.md`, `rich-rendering.md`, `oci-media-types.md`,
  `documentation.md`.
- [podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html) —
  search paths, drop-ins, service types.
- [systemd.exec(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html) —
  `Environment=`, variable expansion in command lines.
- [Margo application description](https://docs.margo.org/specification/applications/application-description) —
  `parameters`, `targets`, `pointer`, `configuration`, `schema`.
