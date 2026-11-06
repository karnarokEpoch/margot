# Sprint 18 — `margot install` without the systemctl binary: D-Bus transport, `--no-reload`, container use

**Status:** draft — design proposed to the owner, awaiting approval; not started
**Type:** feature
**Owner:** python-dev (docs: docs-writer)
**Release:** planned for `release/X.Y.Z` (TBD). Independent of Sprints 14–17.

---

## 1. Goal

`margot install` works from the published container image. It talks to the systemd user manager over its
D-Bus socket instead of running `systemctl --user`, and a new `--no-reload` flag lets it only place files
and touch systemd not at all.

---

## 2. Context

`infra/systemd.py` shells out to `systemctl --user` for three things (see Sprint 13 and
`docs/commands/install.md`):

| Step | Call today | Where |
|---|---|---|
| Session check | `systemctl --user show-environment` | `ensure_user_session()`, first line of `apply_install` |
| Reload | `systemctl --user daemon-reload` | `daemon_reload()`, after files are written |
| Service check (guard 3) | `systemctl --user cat <service>` | `unit_is_known()`, once per expected service |

A fourth call, the Quadlet generator dry-run (`/usr/libexec/podman/quadlet -dryrun -user`), is a local
binary, not systemd. It is already optional (a missing binary gives one warning).

In the published image (`python:3.12-alpine`, entrypoint `margot`) there is no `systemctl`, so
`user_argv()` raises `SystemdError` before anything is written. Mounting the directories and setting the
env vars cannot fix that.

### Verified facts (spike, 2026-11-05, Fedora 43, systemd 258)

- The user manager answers D-Bus on `$XDG_RUNTIME_DIR/systemd/private` (a peer-to-peer socket: no
  `Hello()`, and a `Hello()` call is answered `UnknownObject`) and on the session bus
  `$XDG_RUNTIME_DIR/bus` (needs `Hello()`).
- Over the private socket, with jeepney's sans-IO API only (`jeepney.auth.Authenticator`,
  `jeepney.low_level.Parser`, `Message.serialise`), these worked: `Properties.Get(Manager, Version)`,
  `Properties.Get(Manager, Environment)`, `Manager.LoadUnit(<name>)` then `Properties.Get(Unit, LoadState)`
  (`not-found` for an unknown service, `loaded` + a `FragmentPath` for a known one), and `Manager.Reload()`
  (empty reply once the reload is done).
- jeepney 0.9's blocking `open_dbus_connection()` always sends `Hello()`, so it cannot be used for the
  private socket. Use the sans-IO pieces over a plain `socket.socket(AF_UNIX)`.
- Rootless container, default user namespace: the process is uid 0, sd-bus sends `AUTH EXTERNAL` with
  uid 0, systemd compares with the host uid 1000 and answers `REJECTED`. With `--userns=keep-id` the
  uid is 1000 and the answer is `OK`. So `--userns=keep-id` is a hard requirement of container use.
- On SELinux hosts, a socket bind-mount also needs `--security-opt label=disable`.

---

## 3. Authoritative Design

### Item 1 — D-Bus transport replaces `systemctl`

- Scope: `infra/systemd.py` and a new small `infra/dbus.py`. `systemctl` is no longer called or looked up.
  No fallback to the binary: one code path.
- **`infra/dbus.py`** — a blocking, peer-to-peer D-Bus client over `AF_UNIX` built on jeepney's sans-IO
  API. It authenticates (EXTERNAL, the process uid), optionally sends `Hello()` (session bus only), sends a
  method call, reads until the reply with the matching serial, and raises `DBusError` for an error reply,
  a closed socket, or a timeout. No `rich`/`console` use beyond `console.debug` per call.
- **Address resolution** (`infra/systemd.py`), in order, first that connects wins:
  1. `<runtime>/systemd/private` — `<runtime>` is `$XDG_RUNTIME_DIR`, else `/run/user/<uid>`.
  2. The `unix:path=` part of `$DBUS_SESSION_BUS_ADDRESS`, if set (with `Hello()`).
  3. `<runtime>/bus` (with `Hello()`).
  Abstract-socket addresses (`unix:abstract=`) are not supported; they are skipped.
- **Public functions keep their names and contracts** so services and commands do not change:
  - `ensure_user_session()` — connect, read the Manager `Environment` property. Any failure raises
    `SystemdError("The systemd user session is not reachable at <tried addresses>. …")`. The message names
    `XDG_RUNTIME_DIR` and `--no-reload`.
  - `daemon_reload()` — `Manager.Reload()`; a D-Bus error raises `SystemdError`. Timeout 120 s (existing
    `_TIMEOUT_SECONDS`).
  - `unit_is_known(service)` — `Manager.LoadUnit(service)`, then `Unit.LoadState`; known = `LoadState` is
    not `not-found`.
  - `quadlet_binary()`, `check_units()`, `GeneratorRun`, `run()` — unchanged (the generator is a binary).
  - `user_argv()` is removed (no remaining caller).
- Dependency: `jeepney` (pure Python, no transitive dependencies, MIT) added to `pyproject.toml` and
  `uv.lock`. Import selectively (`from jeepney.low_level import Parser`, …).
- Layering: `infra/` only; `services/install.py` and `commands/install.py` keep calling the same
  `systemd.*` functions.
- Exit codes: unchanged. A `SystemdError` stays exit 1.

### Item 2 — `--no-reload`

- New option on `install`: `--no-reload` (bool, default off). Help: "Place the files only. Do not contact
  systemd: no session check, no daemon-reload, no service check."
- With the flag, `apply_install` skips `ensure_user_session()`, `daemon_reload()` and `_verify_services()`.
  Everything else is unchanged: ownership check, marker, file placement, stale-file removal, and guards 1
  and 2 (pure file/binary work, they already run in `prepare_install`).
- `InstallResult` gains `reloaded: bool`. With `--no-reload`, `services` / `start_services` /
  `wanted_services` are computed from the plan (deferred services excluded), as they are not verified.
- Output: the "Next steps" block starts with `systemctl --user daemon-reload` when `reloaded` is false,
  with a line saying systemd was not contacted, then the usual start/status commands.
- `--dry-run` never contacts systemd; `--dry-run --no-reload` is accepted and behaves as `--dry-run`.
- There is no automatic fallback: an unreachable user manager without `--no-reload` is still exit 1, and
  the message names the flag. The failure happens before anything is written.

### Item 3 — Container use (documented contract, one small code change)

No new option. The contract, documented in `docs/commands/install.md` (new "Running in a container"
section) and mentioned from `docs/guides/getting-started.md`:

- `--userns=keep-id` (required for the D-Bus auth), `--security-opt label=disable` on SELinux hosts, `-it`
  or `--yes` (no terminal otherwise → exit 2).
- Mount the user manager socket at the same path: `$XDG_RUNTIME_DIR/systemd/private`, and set
  `XDG_RUNTIME_DIR`.
- Mount the Quadlet directory at the **same path as on the host** and point `XDG_CONFIG_HOME` at the host's
  config home. margot writes `QUADLET_DIR=<path as margot sees it>` into the drop-ins, and systemd reads
  that value on the host, so the two paths must be equal. A different in-container path produces units that
  point at a missing directory; the docs state this explicitly.
- Optional read-only mounts for a complete guard 1: `$XDG_RUNTIME_DIR/containers/systemd`,
  `/etc/containers/systemd/users`, `/usr/share/containers/systemd/users`. Unmounted roots are silently
  absent from the collision scan.
- The image has no Quadlet generator: guard 2 prints its existing "generator not found" warning. Guard 3
  still works (D-Bus), but its failure message has no generator lines. Make `_missing_message` omit the
  `QUADLET_UNIT_DIRS=… quadlet -dryrun` hint when `quadlet_binary()` is None.
- Example `podman run` with every mount, and an equivalent `--no-reload` example for a host without a
  reachable user manager.

### Non-goals

- A `--quadlet-dir` / host-path remapping option (backlog if the same-path mount proves painful).
- Running the Quadlet generator over D-Bus (not possible; its diagnostics go to the journal).
- System (root) manager support, `unix:abstract=` addresses, `unix:` over TCP, or any `systemctl` fallback.
- Starting, enabling or stopping units (still never done).

---

## 4. Checkable Steps

TDD: write each test before or with its implementation. Exit-code tests follow `code-conventions.md`.

### Branch split (one item → one branch → one worktree)

All branches start from `docs/sprint-18-plan` (this file's branch, cut from `main`). Never work on `main`.

| Item | Branch | Worktree | Owns |
|---|---|---|---|
| 2 — `--no-reload` | `feat/install-no-reload` | `.wk-noreload` | `commands/install.py`, `apply_install` / `InstallResult` / `_next_steps` in `services/install.py`, the flag and next-steps docs |
| 1 — D-Bus transport (+ `_missing_message` change) | `feat/install-dbus` | `.wk-dbus` | `pyproject.toml`, `uv.lock`, `infra/dbus.py`, `infra/systemd.py`, `_missing_message`, existing systemd test fixtures, the guard 3 docs wording |
| 3 — container docs | `docs/install-container` | `.wk-containerdocs` | the "Running in a container" section and the getting-started pointer. Starts after items 1 and 2 are merged. |

Rules that keep items 1 and 2 from conflicting:

- Item 2 never edits an existing systemd fixture or test file. Its tests go in **new files**
  (`tests/integration/test_install_no_reload.py`, `tests/e2e/test_install_no_reload_cli.py`) with their own
  fixture that patches the **public** functions (`margot.infra.systemd.ensure_user_session`, `daemon_reload`,
  `unit_is_known`), whose names item 1 keeps. Item 2 does not touch `infra/systemd.py`.
- `apply_install(..., reload: bool = True)` and `InstallResult.reloaded: bool = True` have defaults, so no
  existing call site or test changes.
- Item 1 does not edit `commands/install.py` or `apply_install`. In `services/install.py` it touches only
  `_missing_message`.
- `docs/commands/install.md`: item 2 edits the synopsis, flag table and "Running the workload"; item 1 edits
  Guard 3 and Limitations. Different hunks.
- The new session-error message in item 1 names `--no-reload`. **Merge order: item 2, then item 1**, so the
  flag exists whenever the message appears.

### Item 1

- [ ] Add `jeepney` to `pyproject.toml`; `uv lock`.
- [ ] `infra/dbus.py` + unit tests against a stub AF_UNIX server thread in `tmp_path` (auth OK/REJECTED,
  method return, error reply, closed socket, timeout, `Hello()` on/off).
- [ ] Rewrite `infra/systemd.py` session check, reload and `unit_is_known` on top of it; address
  resolution + tests (order, missing `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, abstract skipped).
- [ ] Update test fixtures that patch `margot.infra.systemd.which` / `run` for systemctl
  (`tests/unit/test_infra_systemd.py`, `tests/integration/test_install_{apply,guards,parameters}.py`,
  `tests/e2e/test_install_cli.py`) to patch the new functions. `run` stays for the generator.
- [ ] Remove `user_argv()` and its tests.

### Item 2

- [ ] `commands/install.py`: `--no-reload` option, passed to `apply_install(prepared, root=…, reload=…)`.
- [ ] `services/install.py::apply_install`: skip session check / reload / verify; set `reloaded`.
- [ ] `_next_steps`: daemon-reload line when not reloaded.
- [ ] Tests: apply with the flag never calls the systemd functions (assert not called), files and marker
  identical to a normal install; e2e: flag accepted, output shows the daemon-reload line; unreachable
  manager without the flag exits 1 with a message that names `--no-reload`; `--dry-run --no-reload`.

### Item 3

- [ ] `_missing_message`: drop the generator hint when there is no generator binary + test.
- [ ] Docs (docs-writer): `docs/commands/install.md` — synopsis/flag table, "Running in a container",
  guard 3 wording (no longer `systemctl --user cat`), exit-code table, limitations;
  `docs/guides/getting-started.md` pointer. `make docs-check` passes.
- [ ] Manual check, recorded in the final report: the published-image build (`Containerfile`) runs
  `install --yes` against the host user manager with the documented `podman run` command.

---

## 5. Definition of Done

- [ ] All checkable steps completed.
- [ ] `make check` passes (lint + tests, coverage ≥ 90 %).
- [ ] `make docs-check` passes.
- [ ] No `systemctl` lookup or subprocess call remains in `src/` (`grep -rn systemctl src/` shows only
  user-facing text such as the printed next steps and messages).
- [ ] Each item committed as one or more conventional commits (`feat(install): …`, `test(install): …`,
  `docs(install): …`); no bulk commit.
- [ ] Handed back for review (Gate 2). The agent does not push or open PRs.

---

## 6. Close-out Note

```
Merged as commit [hash]. Backfilled ROADMAP Completed table with [release link].
Sprint file deleted via chore(sprint) commit [hash].
```

---

## References

- [sprint-workflow skill](../skills/sprint-workflow/SKILL.md)
- [ROADMAP.md](../../ROADMAP.md)
- `docs/commands/install.md` — shipped behaviour of `install` (Sprint 13).
- `.kiro/steering/code-conventions.md` — console, imports, exit-code rules.
