# margot install

Install one quadlet deployment profile of a Margo application on this host.

```text
margot install [URI] [--project-dir DIR] [--build-dir DIR] [--profile ID]
               [--set NAME=VALUE]...
               [--yes|-y] [--dry-run] [--no-reload]
```

`install` places the unit files and bundled resources of one quadlet deployment profile into
`~/.config/containers/systemd/<application-id>/` and reloads systemd. It never starts,
enables, stops, or restarts any service: after a successful install it prints the
`systemctl --user start` commands for you to run. With `--no-reload`, systemd is not contacted
at all.

## Flags

| Argument / option   | Default | Description                                                                          |
| ------------------- | ------- | ------------------------------------------------------------------------------------ |
| `URI`               | —       | OCI reference of a margo artifact (`oci://` optional). Selects remote mode.          |
| `--project-dir DIR` | `.`     | Project directory. Mutually exclusive with `URI`.                                    |
| `--build-dir DIR`   | `.dist` | Build output directory for project mode. Rejected with `URI`; exit 2 in static mode. |
| `--profile ID`      | auto    | Deployment profile `id` to install.                                                  |
| `--set NAME=VALUE`  | —       | Value for a descriptor parameter (repeatable; last value wins).                      |
| `--yes`, `-y`       | off     | Skip the confirmation prompt.                                                        |
| `--dry-run`         | off     | Resolve, stage, and validate; show the plan; change nothing on the host. Exits 0.    |
| `--no-reload`       | off     | Place the files only. Do not contact systemd: no session check, no daemon-reload, no service check. |

## Source detection

margot infers the source from the arguments — no mode flag:

| Situation                                                       | Source                                              |
| --------------------------------------------------------------- | --------------------------------------------------- |
| `URI` given                                                     | Remote OCI artifact                                 |
| No `URI`; `margo.yaml` present in `--project-dir`               | Built project (build output only)                   |
| No `URI`; no `margo.yaml`; `app.yaml` or `margo/app.yaml` found | Static folder (e.g. from `margot pull --recursive`) |
| None of the above                                               | Error, exit 3 (lists the paths tried)               |

Remote install works for any valid margo artifact, including artifacts not produced by margot.

Project mode never falls back to the registry: it installs exactly what `margot build` produced.
A component that the build directory does not contain fails the install (exit 3, names the component).

## Profile selection

Only `quadlet` profiles are installable.

- **`--profile ID` given:** the profile must exist and must be `type: quadlet`. A `compose`
    profile is refused with "not supported yet"; a `helm` profile is refused with "not supported".
- **`--profile` not given:** if exactly one quadlet profile is present, it is selected and named
    in the plan. Multiple quadlet profiles → exit 3 (lists the ids). No quadlet profile → exit 3.

Every component of the selected profile must have a name and `properties.repository` +
`properties.revision`. A component located by `packageLocation` is refused (exit 3, naming the
component). All checks run before anything is staged.

## Install directory

Files are placed in `$XDG_CONFIG_HOME/containers/systemd/<application-id>/`
(default `~/.config/containers/systemd/<application-id>/`).

All components of the profile are merged into that one flat directory. Relative paths inside the
archives are preserved so `Volume=./nginx.conf:…` in a unit resolves against the unit's own
directory after install.

### Ownership and upgrade

| Situation                                           | Behaviour                                                             |
| --------------------------------------------------- | --------------------------------------------------------------------- |
| Directory absent                                    | Fresh install                                                         |
| Directory present, margot marker, same profile      | Upgrade: updates files, removes files the new payload no longer ships |
| Directory present, margot marker, different profile | Refused; names the recorded profile (exit 3)                          |
| Directory present, no margot marker                 | Refused: "not installed by margot" (exit 3)                           |

On upgrade, files that margot did not write (e.g. a hand-written `90-local.conf` drop-in) are
never touched or deleted.

## Ownership marker

margot writes `.margot-install.json` inside the application directory. Fields:

| Field                            | Value                                                                              |
| -------------------------------- | ---------------------------------------------------------------------------------- |
| `schema`                         | `1`                                                                                |
| `state`                          | `installing` → `installed`                                                         |
| `appId`, `appName`, `appVersion` | From the descriptor                                                                |
| `profileId`                      | The installed profile id                                                           |
| `installedAt`                    | UTC ISO 8601 timestamp                                                             |
| `source`                         | `kind` (`project` / `static` / `remote`) + URI or path                             |
| `components[]`                   | `name`, `revision`, `archiveSha256`, `files[]` (relative paths, drop-ins included) |
| `services[]`                     | Generated service names                                                            |
| `parameters[]`                   | Names of applied parameters (never values)                                         |

## Parameters

The Margo spec's `parameters[].targets[].pointer`, for a quadlet component, is the name of an
**environment variable of the systemd unit** of the target component. It must match
`[A-Za-z_][A-Za-z0-9_]*`. margot writes it into a systemd drop-in beside each unit of the
component.

### How a unit consumes a parameter

Write `${NAME}` (with braces) in any unit field that systemd expands. systemd substitutes
the value as a single argument at start time, even when it contains spaces. Bare `$NAME`
(no braces) is word-split — use `${NAME}` unless you want word-splitting.

A bare `Environment=NAME` in `[Container]` passes the unit-level value into the container:

```ini
[Container]
Image=docker.io/library/nginx:1.27.0
PublishPort=${NGINX_PORT}:80
Environment=NGINX_PORT
Volume=${QUADLET_DIR}/nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

The expansion happens at start time (systemd), not at install time (margot).
An `${NAME}` that has no value expands to the empty string and the unit still starts — see
[Limitations](#limitations).

### Drop-in file

For each unit `U.<suffix>` of the component, margot writes:

`U.<suffix>.d/50-margot-parameters.conf` (mode `0600`):

```ini
# Managed by margot - regenerated on every install.
# Add your own overrides in a differently named file (e.g. 90-local.conf).
[Service]
Environment="NGINX_PORT=8080"
Environment="QUADLET_DIR=/home/user/.config/containers/systemd/com-example-nginx"
```

Variables are sorted alphabetically. The file is regenerated on every install.

A unit file that two components of the same profile both ship receives the variables of both
components. Two components may ship the same file only when they come from the same artifact. If
the two components bind one variable on that unit to different values, the install fails with
exit 3 before any file is written to the host, and the message names the unit and the variable;
identical values are accepted.

A user drop-in with a later-sorting name (e.g. `90-local.conf`) overrides margot's values —
margot never touches files it did not write, so hand-edited drop-ins survive upgrades.

`systemctl --user cat <service>` shows the drop-in lines merged into the generated unit (Quadlet
merges drop-ins before generating the service, so they appear inside the unit body, not as a
separate drop-in block). To see resolved values:

```bash
systemctl --user show -p Environment nginx.service
```

### Values

| Source                   | Rule                                                                         |
| ------------------------ | ---------------------------------------------------------------------------- |
| `--set NAME=VALUE`       | Wins over the descriptor; NAME must be an applicable parameter (else exit 3) |
| Descriptor `value` field | Used when no `--set`; boolean → `true`/`false`, number → decimal             |
| Neither                  | Not applied; listed in a warning on stderr                                   |

Array values in the descriptor are refused for quadlet (exit 3). A `--set` value replaces an
array default. Values containing a newline, carriage return, or NUL are refused (exit 3).

### QUADLET_DIR

margot always writes `Environment="QUADLET_DIR=<absolute application directory>"` into the
drop-in of every unit of every selected component, with or without descriptor parameters.
This lets a unit reference bundled files without hard-coding the install path:

```ini
[Container]
Volume=${QUADLET_DIR}/nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

A unit authored for `podman quadlet install` (which places files flat into
`~/.config/containers/systemd/`) may set its own `QUADLET_DIR` default in `[Service]`. margot's
drop-in overrides it because drop-ins are merged after the unit's own `[Service]` section.

`QUADLET_DIR` is reserved: a descriptor parameter whose `pointer` is `QUADLET_DIR` is refused
(exit 3). `--set QUADLET_DIR=…` is not a recognised parameter name and is refused (exit 3).

## Plan and confirmation

Before touching the host, `install` shows the plan:

```text
╭─ Install plan ─────────────────────────────────────────────────╮
│ application  com-example-nginx                                  │
│ name         NGINX · 1.0.0                                      │
│ profile      com-example-nginx-quadlet · quadlet                │
│ source       project · .dist/1.0.0/margo/app.yaml              │
│ target       /home/user/.config/containers/systemd/com-example-nginx │
│ Components (1)                                                  │
│ └── com-example-nginx-quadlet · .dist/1.0.0_quadlet/...tgz     │
│     ├── archive sha256 <hex>                                    │
│     ├── files: nginx.conf · nginx.container · ...              │
│     └── services: nginx.service                                 │
╰─────────────────────────────────────────────────────────────────╯
margot sets QUADLET_DIR=<target> for every unit.
```

If parameters apply, a parameter table is also shown:

```text
┏━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ parameter ┃ value ┃ source     ┃ variable   ┃ units         ┃
┡━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ nginxPort │ 8080  │ descriptor │ NGINX_PORT │ nginx.service │
└───────────┴───────┴────────────┴────────────┴───────────────┘
```

Then the hint: `install does not schema-validate the descriptor; run margot verify first.`

`--dry-run` exits after the plan (exit 0, nothing written; guards 1 and 2 still run).

Without `--dry-run` and without `--yes`, margot prompts:

```text
Install N component(s) on this host? [y/N]
```

Entering `y` or `yes` (case-insensitive) confirms. Anything else, including EOF, declines →
`"Aborted: nothing was installed"`, exit 1.

When stdin is not a terminal, pass `--yes` (CI) or `--dry-run`; without either, margot exits 2.

## Safety checks

Three guards run as part of an install. Guards 1 and 2 run before any file is written
(including during `--dry-run`). Guard 3 runs after the `daemon-reload`.

### Guard 1 — unit-name collision

Every unit file to install is checked against the full Quadlet search path (six roots,
scanned recursively):

1. `$XDG_RUNTIME_DIR/containers/systemd`
2. `$XDG_CONFIG_HOME/containers/systemd` (default `~/.config/containers/systemd`)
3. `/etc/containers/systemd/users/$UID`
4. `/etc/containers/systemd/users`
5. `/usr/share/containers/systemd/users/$UID`
6. `/usr/share/containers/systemd/users`

A collision is either:

- **Same file name** — another application has a unit file with the same name anywhere in the
    search path (outside this application's own directory).
- **Same generated service name** — `<name>.kube` and `<name>.container` both produce
    `<name>.service`. Installing one when the other is already present is refused.

Files inside this application's own directory are an upgrade and are never flagged. The error
names both file paths. margot never renames or shadows a unit.

### Guard 2 — Quadlet generator dry-run

margot runs the Quadlet generator in dry-run mode (`/usr/libexec/podman/quadlet -dryrun -user`)
against the staged tree (units, bundled files, and drop-ins). A non-zero exit fails the install
(exit 3) with the trimmed generator output. Nothing is written to the host.

If the generator binary is not found, one warning is printed and install continues.

References to units outside the staged tree (`Network=`, `Volume=`, `Pod=`, etc.) are the unit
author's responsibility:

- A referenced unit that is already installed on the host → silent.
- A referenced unit that is not installed → one warning printed; the service is generated once
    that unit is installed and systemd is reloaded.

### Guard 3 — post-reload verification

After `daemon-reload`, each expected service must be known to systemd
(`systemctl --user cat <service>` exits 0). If a service is missing:

- Explanation is reference-only (an unresolved unit from guard 2) → warning; service is
    deferred until the referenced unit is installed.
- Any other reason → exit 1; the error names the service, the unit file, and the hint to
    inspect with `QUADLET_UNIT_DIRS=<app-dir> /usr/libexec/podman/quadlet -dryrun -user` or
    `journalctl --user -b -t quadlet-generator`. Files are **not** rolled back.

## Running the workload

`install` prints the commands but never runs them:

```text
Next steps. install did not start anything; run these yourself:
  systemctl --user start nginx.service
  systemctl --user status nginx.service
```

Only `.container`, `.kube`, and `.pod` services need a manual `systemctl --user start`. Volume,
network, image, build, and artifact units are started as dependencies of the services that
use them.

For units that declare `WantedBy=default.target` in their `[Install]` section, `install` adds:

```text
nginx.service starts at the next login/boot. Without a login, boot starts it only with
lingering (loginctl enable-linger).
```

`install` never runs `systemctl enable`. The Quadlet generator creates the
`default.target.wants/` symlink itself; `systemctl --user is-enabled <service>` reports
`generated`.

With `--no-reload`, `install` does not contact systemd. It places the files and prints the
daemon-reload command first. Run that command yourself before the start commands, because
systemd does not know the new units until it reloads:

```text
Next steps. systemd was not contacted (--no-reload), so reload it first. install did not start anything; run these yourself:
  systemctl --user daemon-reload
  systemctl --user start nginx.service
  systemctl --user status nginx.service
```

### Tips (not shown by install)

- A first start may pull images from the registry. If it exceeds systemd's default 90 s start
    timeout, add `TimeoutStartSec=300` to the unit's `[Service]` section or a user drop-in.
- After upgrading a running application with `margot install`, the running service keeps its
    old unit until restarted: `systemctl --user restart <service>`.
- Parameter values are clear text. Inspect them with
    `systemctl --user show -p Environment <service>` or `podman inspect`.

## Service name reference

| Unit file          | Generated service         | Start needed?                         |
| ------------------ | ------------------------- | ------------------------------------- |
| `<name>.container` | `<name>.service`          | yes                                   |
| `<name>.kube`      | `<name>.service`          | yes                                   |
| `<name>.pod`       | `<name>-pod.service`      | no; started by a member container     |
| `<name>.volume`    | `<name>-volume.service`   | no; pulled in by dependents           |
| `<name>.network`   | `<name>-network.service`  | no; pulled in by dependents           |
| `<name>.image`     | `<name>-image.service`    | oneshot pull; pulled in by dependents |
| `<name>.build`     | `<name>-build.service`    | oneshot; pulled in by dependents      |
| `<name>.artifact`  | `<name>-artifact.service` | oneshot; pulled in by dependents      |

`podman quadlet list` shows margot-installed units with an empty APPLICATION column. margot's
per-application subdirectory layout and `podman quadlet install`'s flat layout coexist.

## Exit codes

| Code | Situation                                                                                                                                             |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`  | Successful install, or `--dry-run` completed                                                                                                          |
| `1`  | User declined confirmation ("Aborted: nothing was installed")                                                                                         |
| `1`  | systemd user session is unusable                                                                                                                      |
| `1`  | `daemon-reload` failed                                                                                                                                |
| `1`  | Expected service unknown to systemd after `daemon-reload`                                                                                             |
| `2`  | `URI` given with `--project-dir` or `--build-dir`                                                                                                     |
| `2`  | `--build-dir` given outside project mode                                                                                                              |
| `2`  | `--set NAME` without `=`                                                                                                                              |
| `2`  | No terminal and neither `--yes` nor `--dry-run`                                                                                                       |
| `3`  | No descriptor found (lists the paths tried)                                                                                                           |
| `3`  | Unknown, non-installable, or ambiguous profile                                                                                                        |
| `3`  | Component problem: no OCI coordinates, `packageLocation`, or unsafe name                                                                              |
| `3`  | Archive missing, not a tar, no quadlet unit at root, or hostile archive                                                                               |
| `3`  | Two components ship the same relative path                                                                                                            |
| `3`  | Application directory exists without margot marker, or holds a different profile                                                                      |
| `3`  | Parameter error: unknown `--set` name, reserved pointer (`QUADLET_DIR`), same pointer on two parameters, array value, or forbidden character in value |
| `3`  | Unit-name collision (file name or generated service name)                                                                                             |
| `3`  | Quadlet generator rejected the unit files                                                                                                             |
| `4`  | Registry or credential failure                                                                                                                        |

## Examples

```bash
# Install from a built project (build first, then install)
margot build -t all && margot install

# Show the plan without changing the host
margot install --dry-run

# Install from a pulled static folder
margot pull public.ecr.aws/g2n4p2m7/margo:1.0.0 --recursive
margot install

# Install directly from a remote artifact
margot install public.ecr.aws/g2n4p2m7/margo:1.0.0

# Override a parameter value
margot install --set nginxPort=9090

# Override a parameter value (dry run to see the plan)
margot install --dry-run --set nginxPort=9090

# Install a specific profile when the application ships more than one quadlet profile
margot install --profile com-example-nginx-quadlet

# Non-interactive install (CI / scripts)
margot install --yes

# Place the files without contacting systemd; run daemon-reload yourself afterwards
margot install --yes --no-reload
```

## Limitations

- Compose and Helm profiles are not installable. `compose apply` is a future release; Helm
    requires a cluster outside the scope of this command.
- Components located by `packageLocation` + `keyLocation` are not supported. Only OCI
    components (`properties.repository` + `properties.revision`) can be installed.
- All units of a component receive all of its parameter variables. Per-unit variable targeting
    within a single component is not supported.
- `--set` values are not validated against the descriptor schema (`dataType`, `minValue`, etc.).
- An `${NAME}` in a unit file that has no value expands silently to the empty string at
    start time. The unit still starts and no warning is printed.
- The descriptor is not schema-validated by `install`. Run `margot verify` first.
- With `--no-reload`, systemd is not contacted, so the services are unverified: `install` does not
    check that systemd knows them. Run `systemctl --user daemon-reload` and then
    `systemctl --user status <service>` to confirm each one.
- Rootless user session only. Root and system-wide installs are not supported.
- Parameter values are clear text. There is no secret store.
- There is no `uninstall`, `list`, or `status` command yet. To remove an installed application:
    stop the service(s), delete the application directory, and run
    `systemctl --user daemon-reload`.
- No rollback after a partial failure. Files already written are not removed. Re-run `install`
    after fixing the cause.
- No `--start`, `--force`, `--json`, or `--type` flags.
