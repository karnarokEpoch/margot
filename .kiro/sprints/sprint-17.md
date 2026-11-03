# Sprint 17 — OS trust store and per-registry CA trust from `certs.d`

**Status:** draft — design settled with owner (2026-10-17, rev. 2: stdlib `SSLContext` approach); not started
**Type:** feature
**Owner:** python-dev (docs: docs-writer)
**Release:** planned for `release/X.Y.Z` (TBD). Independent of Sprints 11–16; can ship before or after them.

---

## 1. Goal

margot verifies registry TLS certificates against the **operating-system trust store** plus the extra
CA certificates that Podman, Buildah and Skopeo already trust for a registry, read from
`containers-certs.d(5)` directories. A registry that works with `podman pull` then also works with
`margot fetch` / `pull` / `push` / `auth` / `package` with no margot-specific configuration, and
margot no longer uses the bundled `certifi` CA file.

---

## 2. Context

Today margot has no TLS configuration. All registry traffic goes through oras-py, which uses
`requests`. The trust store is therefore whatever `requests` uses: the `REQUESTS_CA_BUNDLE` /
`CURL_CA_BUNDLE` file if set, otherwise the `certifi` bundle shipped inside the Python environment. It
is **not** the OS store, and it does **not** read `certs.d`. A private registry whose CA is installed
only under `~/.config/containers/certs.d/<host>:<port>/ca.crt` (the Podman way), or only in the OS
store, fails TLS verification in margot while working in Podman.

### Design history (owner rulings)

- Replacing `requests` with `httpx` was considered and **rejected for this sprint** (2026-10-17).
  Reasons verified by investigation: `requests` stays installed regardless (`docker`, `podman`,
  `linkml`, `oras` all require it); oras-py's HTTP layer (`provider.py`, `auth/*`, `decorator.py`) is
  built on `requests.Session`, so httpx means replacing oras-py's transport, which is a separate,
  much larger piece of work (ROADMAP backlog: "Registry transport"); and httpx 0.28 still uses
  `certifi` by default, so it would not by itself remove the bundled CA file.
- Shipping a temp CA bundle file per host (base roots + extra CAs, passed as `verify=<path>`) was
  rejected: it always carries a CA file even when none is needed, needs cleanup, and mutates shared
  client state. This sprint uses an in-memory `ssl.SSLContext` per registry instead.

### Investigation findings (constrain the design)

- Spike (2026-10-17, requests 2.34.2): a `requests.Session` with an `HTTPAdapter` whose pool manager
  is given `ssl_context=<ssl.SSLContext>` verifies a server signed by a private CA, **even when
  `verify=True` is passed per request**, which is exactly how oras-py calls
  (`session.request(..., verify=self._tls_verify)`). Without the adapter, the same request fails.
- `ssl.create_default_context()` loads the OS trust store through OpenSSL's default paths and honors
  `SSL_CERT_FILE` / `SSL_CERT_DIR`. On the reference Fedora host it loaded 148 CAs and reached
  `public.ecr.aws`. Extra CAs are added with `load_verify_locations(cafile=…)`.
- oras-py keeps one `requests.Session` per client and shares it with the auth backend, so a
  mounted adapter covers registry requests **and** token-realm requests (often a different host).
- Every client is built from `infra/oci.py::OrasClient`, including host-less ones
  (`OrasClient()` in `services/package.py` and `services/auth.py`), so mounting in `__init__`
  covers all of them.
- `requests.exceptions.SSLError` is a `RequestException`, so commands already map a TLS failure to
  exit code **4** (remote / authentication failure). No exit-code change.
- `--plain-http` (Sprint 15) is designed but not built. Only the `https://` prefix gets the adapter,
  so plain HTTP is untouched by construction.

Authoritative references: `containers-certs.d(5)`
(<https://man.archlinux.org/man/containers-certs.d.5.en>), `.kiro/steering/code-conventions.md`
(exit-code taxonomy, console rules), `.kiro/steering/structure.md`.

---

## 3. Authoritative Design

### 3.1 Scope

#### In scope

- Base trust = OS trust store (stdlib default context), instead of `certifi`.
- Discover per-registry CA certificates (`*.crt`) from the `certs.d` directories and add them to the
  trust used for connections to that registry.
- Applies to every request made through `infra/oci.py::OrasClient`, including token-realm requests
  and redirect hops.
- Debug logging of what was found; a hint on TLS verification failure; documentation.

#### Out of scope / non-goals (owner rulings, 2026-10-17)

- **No override.** No `--certs-dir` flag, no `MARGOT_CERTS_DIR` env var, no `settings.toml` field.
  Discovery is automatic only. Tests monkeypatch the search roots.
- **Client certificates deferred.** `*.cert` / `*.key` files are ignored (mTLS is a ROADMAP follow-up).
- **No `httpx` migration** and no replacement of oras-py (ROADMAP backlog).
- **No `truststore` dependency.** The stdlib OS default paths are enough on the reference platform
  (Linux with rootless Podman). macOS / Windows system stores are not a goal of this sprint.
- No `--insecure` / TLS-verification skip.
- No change to the helm path (Sprint 15 introduces `infra/helm.py`; see §3.7).
- `margot install` (Sprint 13) is unaffected: it calls Podman, which reads `certs.d` itself.

#### User-visible behavior change to document

The base trust changes from the `certifi` bundle to the OS store. Hosts signed by public CAs keep
working. A site that worked only because `certifi` trusts a CA the OS does not is expected to be
rare; the release notes and `docs/config.md` say so.

### 3.2 Directory lookup — `domain/` (pure)

New pure function(s) in `domain/` (suggested module `domain/certs.py`; no I/O, no `rich`, no
`console`):

- Given a registry authority (`host` or `host:port`, exactly as in the request URL), return the
  **directory name** to look for. The man page is explicit: the port part must match **exactly** as
  written. `registry.example` and `registry.example:443` are different directories; there is **no**
  default-port equivalence.
- Docker Hub: the user types `docker.io/...` but requests go to `registry-1.docker.io` (normalized in
  `OrasClient.get_container`). The candidate list for `registry-1.docker.io` therefore also contains
  the aliases from `_DOCKER_HUB_ALIASES` in `domain/uri.py`, requested host first. Every other host
  yields a single candidate.
- Classify a directory listing: names ending in `.crt` are CA certificates (returned sorted, for a
  deterministic result); everything else is ignored in this sprint.

### 3.3 Search roots and precedence — `infra/tls.py` (new, I/O)

Directories are consulted in the order given by the current `containers-certs.d(5)` (highest priority
first). Implement as a module-level ordered tuple of root-resolving callables/constants so tests can
monkeypatch it:

1. `$XDG_CONFIG_HOME/containers/certs.d/` (or `$HOME/.config/containers/certs.d/` if unset)
2. rootless (UID > 0): `/etc/containers/certs.rootless.d/<UID>/`, then `/etc/containers/certs.rootless.d/`
3. `/etc/containers/certs.d/`
4. rootless: `/usr/share/containers/certs.rootless.d/<UID>/`, then `/usr/share/containers/certs.rootless.d/`
5. `/usr/share/containers/certs.d/`
6. compatibility fallback: `/etc/docker/certs.d/`

(For UID 0 the rootful variants `certs.rootful.d` replace the rootless ones in items 2 and 4.)

Rule: for a given host, the **first root that contains a directory named for that host wins**; roots
are not merged. The dev agent confirms this against containers/image behavior and records any
deviation in the sprint file before implementing; if containers/image merges, follow it.

Missing roots, unreadable roots and permission errors are not errors: treat as "not found" and log
with `console.debug`.

### 3.4 Contexts and wiring — `infra/tls.py` + `infra/oci.py`

No temp files, no `verify=<path>`, no change to oras-py's `_tls_verify`, no override of `do_request`.

- **Base context:** `ssl.create_default_context()` (OS store, honors `SSL_CERT_FILE` /
  `SSL_CERT_DIR`). Built lazily, once per process.
  - Safety net for Python builds whose OpenSSL default paths are empty: if
    `cert_store_stats()["x509"] == 0`, probe well-known bundle paths in order
    (`/etc/pki/tls/certs/ca-bundle.crt`, `/etc/ssl/certs/ca-certificates.crt`, `/etc/ssl/cert.pem`),
    load the first that exists (`console.debug` which one). If none loads, emit one
    `console.warning` that no system CA certificates were found and that `SSL_CERT_FILE` can point
    to a bundle. There is **no** `certifi` fallback.
- **Per-host context:** when a `certs.d` directory matches a host, build a new context from the same
  base recipe and call `load_verify_locations(cafile=<each .crt>)`. Cache by authority. Hosts with no
  match share the base context.
- **Router adapter:** an `HTTPAdapter` subclass (suggested name `CertsDirAdapter`), mounted on the
  session's `https://` prefix in `OrasClient.__init__` (after `super().__init__()`). Its `send()`
  reads the authority from `request.url`, selects (and lazily creates) a stateless sub-adapter whose
  pool manager is built with the matching `ssl_context`, and delegates. Public requests/urllib3 APIs
  only. It also closes its sub-adapters in `close()`. Because selection happens per request, the
  token realm host and each redirect hop get their own `certs.d` lookup, as Podman does.
  - Cache creation is guarded by a lock; the adapter holds no per-request mutable state, so shared
    clients and threads are safe.
- **`REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE`:** requests substitutes these for `verify=True`. The dev
  agent verifies empirically whether the path is then additionally loaded into the adapter's context
  (additive, desired) or ignored. If ignored, load that file into the base context explicitly. The
  documented behavior is: the env bundle adds to the OS store.
- **Dependencies:** `requests>=2.32` becomes a **direct** dependency in `pyproject.toml` (margot now
  imports `requests.adapters`, and already imports `requests.exceptions`). `certifi` is **not** added.
  It stays installed only as a dependency of `requests`; margot never reads it. Dev-only: `trustme`
  (or `cryptography`, if already present) for test certificates.
- Imports follow the selective-import rule. `domain/` imports nothing from `infra/` or `console`.

### 3.5 Diagnostics

- `console.debug` (from `infra/`): the `certs.d` directory chosen for a host and each CA file loaded;
  or "no certs.d entry for `<host>`"; which system bundle was used by the safety net.
- A `.crt` that is unreadable or fails to load (`ssl.SSLError` / `OSError`): `console.warning`
  naming the file, then skip it. At most once per file per process. Owner ruling: warn and skip,
  do not fail hard. The TLS error that follows, if any, carries the hint below.
- On `requests.exceptions.SSLError` raised inside the router adapter's `send()`, re-raise an
  `SSLError` whose message keeps the original text and appends a hint naming the host and the
  location where a private CA can be placed
  (`<first user-level root>/<host[:port]>/ca.crt`), and stating that margot reads the same
  directories as Podman (`containers-certs.d(5)`). Same exception class, so the exit code stays
  **4** and the `--json` envelope `code` stays 4. No hint for non-TLS errors. Since the adapter knows
  the failing host, the hint is correct for realm and redirect hosts too.

### 3.6 Interaction with `--plain-http` (Sprint 15)

The adapter is mounted on `https://` only. When a client talks plain HTTP (oras-py `insecure=True`,
prefix `http`), requests never reach the adapter and no lookup happens. Sprint 15 needs no rework.

### 3.7 Reuse by helm (not in this sprint)

`infra/tls.py` exposes a small frozen result for a host (matched directory, ordered CA file list), in
addition to the context builder, so a later Sprint-15 follow-up can pass the CA to helm
(`--ca-file`) without re-implementing discovery. Do not build any helm integration now.

### 3.8 Error / exit-code table

| Situation | Behavior | Exit |
|---|---|---|
| No `certs.d` entry; host signed by a public CA in the OS store | verifies against the OS store | 0 |
| `certs.d` CA matches the registry | verifies; debug log only | 0 |
| `certs.d` CA present but does not match the server | `SSLError` + hint | 4 |
| No `certs.d` entry; private CA | `SSLError` + hint | 4 |
| Invalid PEM / unreadable `.crt` | warning, file skipped | unchanged |
| `certs.d` root unreadable | debug log, treated as absent | unchanged |
| No system CA found at all | one warning; requests then fail with `SSLError` + hint | 4 |

---

## 4. Checkable Steps

Write tests first (TDD, per `code-conventions.md`). Each step is committed separately with a
conventional-commit message.

### Pure logic (`domain/`)

- [ ] `domain/certs.py`: authority → directory-name rule (exact port match, no 443 equivalence).
- [ ] Docker Hub candidate names (typed alias and `registry-1.docker.io`).
- [ ] `.crt` classification; sorted; `.cert` / `.key` / other files ignored.
- [ ] Unit tests for all of the above.

### I/O (`infra/tls.py`)

- [ ] Ordered search roots (§3.3), monkeypatchable; rootless vs rootful variants; first-hit-wins.
- [ ] Base `SSLContext` with the empty-store safety net (§3.4); warn once when nothing is found.
- [ ] Per-host context: base recipe + each `.crt`; cached per authority; bad file → warn once, skip.
- [ ] `CertsDirAdapter` (router) with sub-adapters per context; lock around creation; `close()`.
- [ ] `SSLError` hint re-raise inside `send()`.
- [ ] Unit tests with `tmp_path` roots and monkeypatched contexts: precedence, no match, missing and
      unreadable roots, bad PEM, empty system store, cache reuse, hint text and host.

### Wiring (`infra/oci.py`)

- [ ] `OrasClient.__init__` mounts the adapter on the session's `https://` prefix (also for
      host-less clients).
- [ ] Regression test: the session used by oras-py's own methods and by the auth backend is the
      mounted one (call through `get_manifest()` / `super().pull()` dispatch with a `Container`,
      not only margot's own call sites).
- [ ] `pyproject.toml`: `requests>=2.32` added; `certifi` not added; `uv.lock` updated; `trustme`
      (or equivalent) added to dev dependencies.
- [ ] Record the `REQUESTS_CA_BUNDLE` finding (§3.4) and the containers/image first-hit-wins
      confirmation (§3.3) in this file.

### Integration

- [ ] In-process HTTPS fake registry (`/v2/`, a manifest, a blob, a token realm on a second
      authority) using a generated private CA.
- [ ] Cases: fails with exit 4 and the hint when no `certs.d` entry exists; succeeds when `ca.crt`
      is in a monkeypatched root under `<host>:<port>`; still fails for a different port; token
      realm on a second host with its own `certs.d` entry succeeds; a public-CA host still verifies
      when an unrelated `certs.d` entry exists (OS roots kept).
- [ ] E2E (`tests/e2e/`): `margot fetch` against the fake registry with and without `certs.d`;
      test names and docstrings state the exit code (`…_exits_4`).

### Docs (docs-writer)

- [ ] `docs/config.md`: new "Registry TLS and `certs.d`" section: OS trust store as base, the lookup
      order, exact-port rule, `.crt` only, no client certificates, no override,
      `SSL_CERT_FILE` / `SSL_CERT_DIR` and `REQUESTS_CA_BUNDLE` behavior, the base-trust change.
- [ ] `docs/concepts.md`: one short paragraph pointing to that section.
- [ ] `docs/exit-codes.md`: add TLS verification failure under code `4`.
- [ ] Correct any docs wording that implies margot uses the OS trust store before this sprint.
- [ ] `make docs-check` passes.

---

## 5. Definition of Done

- [ ] All checkable steps completed, each as one or more conventional-commit commits
      (`feat(tls): …`, `test(tls): …`, `docs: …`).
- [ ] `make check` passes (lint + tests, coverage threshold).
- [ ] `make docs-check` passes.
- [ ] A registry whose CA exists only in `certs.d` works with `fetch`, `pull`, `push` and
      `auth login`; the same registry without the entry fails with exit 4 and the hint.
- [ ] A registry whose CA exists only in the OS store works.
- [ ] No `certifi` import anywhere in `src/`; no temp CA files created.
- [ ] No `TODO` left without the `# TODO(kiro):` format.
- [ ] Handed back for review (Gate 2). The dev agent does not push, open PRs, or manage worktrees.

---

## 6. Close-out Note

Filled in after merge:

```text
Merged as commit [hash]. Backfilled ROADMAP Completed table with [release link].
Sprint file deleted via chore(sprint) commit [hash].
```

---

## References

- `containers-certs.d(5)` — <https://man.archlinux.org/man/containers-certs.d.5.en>
- [ROADMAP.md](../../ROADMAP.md)
- [code-conventions.md](../steering/code-conventions.md) — exit codes, console rules.
- [Sprint 15](./sprint-15.md) — `--plain-http`, `infra/helm.py` (future reuse of discovery).
