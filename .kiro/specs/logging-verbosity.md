# Spec: Logging & Verbosity

**Status:** Ready for implementation  
**Branch target:** `feat/logging-verbosity`

---

## Problem

All output is ad-hoc. Commands use `rprint` and `echo` with inline markup strings.
Services and infra are completely silent — no way to observe steps as they run.
There is no verbosity control: the user sees fixed output with no way to get more or less detail.

Specific pain points today:
- Warnings (e.g. `--force-type implies --force`) are inlined in command code with raw markup strings.
- No step-level feedback during `pull` (fetching manifest, pulling layers, renaming file).
- No way to debug silently failing operations.
- No consistent format: some messages have a `[green]` prefix, others are plain `echo`.

---

## Goals

1. A `--verbose` / `-v` global flag that enables step-level INFO output.
2. All log emission goes through a single `margot.console` module — no more scattered `rprint` / `echo` calls with inline markup.
3. Warnings, info, errors, and success all have a consistent visual format.
4. Services can emit log messages without depending on Rich or Typer — they call a thin interface.
5. No behaviour change when `--verbose` is not set: existing visible output (success lines, errors) stays identical.

---

## Non-goals

- File-based logging (stderr/stdout redirection is enough for CI).
- Log levels beyond three tiers (normal / verbose / debug). No `--quiet` in this iteration.
- Structured/JSON log output.

---

## Design

### Verbosity tiers

Three tiers, two flags:

| Tier | Flag | Content |
|---|---|---|
| **Normal** (default) | — | Success lines, warnings, fatal errors |
| **Verbose** | `--verbose` / `-v` | High-level step info (URI validated, manifest fetched, N layers pulled, file renamed…) |
| **Debug** | `--debug` / `-d` | Low-level infra calls (GET manifest URL, pulling layers from X → Y) |

Debug implies verbose (if `--debug` is set, both `_verbose` and `_debug` are `True`).

> **Rationale for three tiers:** infra-level OCI calls (GET manifest, pull) are meaningfully
> lower granularity than service-level steps. Mixing them under `--verbose` would make normal
> verbose output noisy. A dedicated `--debug` flag keeps them separate and follows standard CLI
> convention (e.g. `curl -v` vs `curl --trace`).

### New module: `src/margot/console.py`

Central output hub. Single source of truth for all terminal output.

#### Stream routing rule

| Function | Stream | Rationale |
|---|---|---|
| `success` | **stdout** | User-facing result. Must be pipeable (`margot pull … > file`). |
| `warning` | **stderr** | Diagnostic. Should not pollute stdout pipelines. |
| `info` | **stderr** | Diagnostic step log. Same rationale as warning. |
| `debug` | **stderr** | Low-level diagnostic. Same rationale. |
| `fatal` | **stderr** | Error. Always stderr. |

Standard Unix convention: program output on stdout, all diagnostics on stderr.
This means `margot pull … > out.txt` captures only pulled file paths — warnings,
step logs, and errors go to the terminal independently.

Two `Console` instances are required: one bound to stdout, one to stderr.

```python
# src/margot/console.py

import sys

from rich.console import Console
from typer import Exit

_stdout = Console(file=sys.stdout)
_stderr = Console(file=sys.stderr)
_verbose: bool = False
_debug: bool = False


def set_verbose(enabled: bool) -> None:
    """Called once by the CLI callback when --verbose is active."""
    global _verbose
    _verbose = enabled


def set_debug(enabled: bool) -> None:
    """Called once by the CLI callback when --debug is active. Implies verbose."""
    global _debug, _verbose
    _debug = enabled
    if enabled:
        _verbose = True


def is_verbose() -> bool:
    return _verbose


def is_debug() -> bool:
    return _debug


def success(message: str) -> None:
    """Green success line → stdout. Always shown."""
    _stdout.print(f"[green]{message}[/green]")


def warning(message: str) -> None:
    """Yellow warning line → stderr. Always shown."""
    _stderr.print(f"[yellow]Warning:[/yellow] {message}")


def info(message: str) -> None:
    """Dim step-level info → stderr. Shown in verbose and debug modes."""
    if _verbose:
        _stderr.print(f"[dim]{message}[/dim]")


def debug(message: str) -> None:
    """Dim low-level infra detail → stderr. Only shown in debug mode."""
    if _debug:
        _stderr.print(f"[dim cyan]debug:[/dim cyan] [dim]{message}[/dim]")


def fatal(message: str) -> None:
    """
    Print a red error line → stderr and immediately exit with code 1.
    Use for unrecoverable errors in commands.
    """
    _stderr.print(f"[red]Error:[/red] {message}")
    raise Exit(1)
```

**Why a module-level singleton?** The verbosity flags are a global CLI concern set once at startup.
Passing them through every service/infra call would pollute every signature. A module-level
flag is the standard pattern for CLI tools (same as Python's `logging.basicConfig`).

**Why two `Console` instances?** Rich's `Console(stderr=True)` shorthand is a read-only attribute
after construction. The clean approach is to construct one `Console` per stream explicitly.

**Layer rule:** `console.py` lives at the root of `margot/` (peer of `main.py`), not inside
any layer. `domain/` must not import it. `services/`, `infra/`, and `commands/` may all import it.

### Global flags

Wired in `main.py` via the existing `app.callback`. The current `version_callback` in
`commands/version.py` is renamed to `global_options` and gains two new parameters:

```python
# commands/version.py  →  renamed to: commands/global_options.py
def global_options(
    version_flag: bool = Option(False, "--version", "-V", help="Print version and exit.", is_eager=True),
    verbose: bool = Option(False, "--verbose", "-v", help="Enable verbose output (step-level info)."),
    debug: bool = Option(False, "--debug", "-d", help="Enable debug output (infra-level detail, implies --verbose)."),
) -> None:
    if debug:
        set_debug(True)
    elif verbose:
        set_verbose(True)
    if version_flag:
        echo(f"margot {get_version()}")
        raise Exit()
```

`main.py` imports and registers `global_options` instead of `version_callback`.

Flag allocation:
- `-V` → `--version`
- `-v` → `--verbose`
- `-d` → `--debug`

### Migration of existing output calls

All existing `rprint(...)` and `echo(...)` (non-error) in `commands/` are replaced with calls
to `console.*`. Mapping:

| Current call | Replacement |
|---|---|
| `rprint("[green]Pulled:[/green] {path}")` | `console.success(f"Pulled: {path}")` |
| `rprint("[yellow]Warning: --force is active...")` | `console.warning("--force is active. Safety checks bypassed.")` |
| `rprint("[yellow]Warning: --force-type implies --force...")` | `console.warning("--force-type implies --force. Safety checks bypassed.")` |
| `rprint("[yellow]No layers pulled.[/yellow]")` | `console.warning("No layers pulled.")` |
| `echo(f"Error: {e}", err=True)` + `raise Exit(1)` | `console.fatal(str(e))` |
| `echo(f"margot {get_version()}")` | keep as `echo(...)` — version output is not a log message |

### `console.info(...)` call sites — services

**`services/pull.py`** — `pull_artifact`:
- After URI validation: `info(f"URI validated: {uri}")`
- After SemVer check passes: `info(f"Tag '{tag}' is valid SemVer.")`
- After `Path(outdir).mkdir`: `info(f"Output directory ready: {outdir}")`
- After `client.get_manifest`: `info("Manifest fetched.")`
- After artifact type detection: `info(f"Detected artifact type: {package_type.value if package_type else 'unknown'}")`
- When `force_type` overrides detected type: `info(f"Artifact type overridden to: {force_type.value}")`
- After `client.pull`: `info(f"Pulled {len(pulled_paths)} layer(s).")`
- After rename in `_apply_payload_naming`: `info(f"Renamed '{old_name}' → '{desired_name}'.")`
- When rename is skipped (no annotation): `info("No title annotation found; keeping original filename.")`

**`services/fetch.py`** — `fetch_manifest`:
- After URI validation: `info(f"Fetching manifest for: {uri}")`
- After fetch returns: `info("Manifest retrieved.")`

### `console.debug(...)` call sites — infra

**`infra/oci.py`** — `OrasClient`:
- In `get_manifest`: `debug(f"GET manifest: {uri}")`
- In `pull`: `debug(f"Pull layers: {uri} → {outdir}")`

### `domain/` stays silent

`domain/` must not import `console`. It raises `ValueError` on bad input. The calling layer
(service or command) decides whether to log the outcome.

---

## File changes summary

| File | Change | Type |
|---|---|---|
| `src/margot/console.py` | **New.** Central output hub with `success`, `warning`, `info`, `debug`, `fatal`. | New |
| `src/margot/commands/global_options.py` | **New.** Rename + extend `version_callback` → `global_options`; add `--verbose`/`--debug`. | New (replaces version.py callback) |
| `src/margot/commands/version.py` | Remove callback, keep only `get_version()` helper. | Modified |
| `src/margot/main.py` | Import and register `global_options` instead of `version_callback`. | Modified |
| `src/margot/commands/pull.py` | Replace all `rprint`/`echo` with `console.*`; `echo(..., err=True)` + `raise Exit(1)` → `console.fatal(...)`. | Modified |
| `src/margot/commands/fetch.py` | Replace `rprint` with `console.*`. | Modified |
| `src/margot/services/pull.py` | Add `console.info(...)` at each step. | Modified |
| `src/margot/services/fetch.py` | Add `console.info(...)` at each step. | Modified |
| `src/margot/infra/oci.py` | Add `console.debug(...)` per OCI call. | Modified |

---

## Testing

### Stream capture approach

`_stdout` and `_stderr` are module-level `Console` instances. Tests replace them with
`Console(file=StringIO())` instances for the duration of a test, then restore the originals.
Provide a fixture in `conftest.py`:

```python
from io import StringIO
import margot.console as _console
from rich.console import Console
from pytest import fixture

@fixture()
def capture_console():
    """Replace _stdout and _stderr with StringIO-backed consoles for assertion."""
    out = StringIO()
    err = StringIO()
    original_stdout = _console._stdout
    original_stderr = _console._stderr
    _console._stdout = Console(file=out)
    _console._stderr = Console(file=err)
    yield out, err
    _console._stdout = original_stdout
    _console._stderr = original_stderr


@fixture(autouse=False)
def reset_console():
    from margot.console import set_debug, set_verbose
    set_verbose(False)
    set_debug(False)
    yield
    set_verbose(False)
    set_debug(False)
```

### Unit — `tests/unit/test_console.py`

- `set_verbose(True)` / `set_verbose(False)` toggle `is_verbose()`.
- `set_debug(True)` sets both `is_debug()` and `is_verbose()` to `True`.
- `set_debug(False)` does not reset `_verbose` if it was independently set.
- `success(...)` writes to stdout, not stderr.
- `warning(...)` writes to stderr, not stdout. Always emits with `Warning:` prefix.
- `info(...)` writes to stderr when verbose, produces no output when not verbose.
- `debug(...)` writes to stderr when debug, produces no output in normal or verbose-only mode.
- `fatal(...)` writes to stderr and raises `Exit(1)`.

### Integration — `tests/integration/test_pull_service.py`

- With `set_verbose(True)`, `pull_artifact(...)` (mocked OrasClient) emits info messages
  on stderr (captured via `capture_console` fixture).
- Verbose stderr includes: "URI validated", "Manifest fetched", "Pulled N layer(s)".
- Verbose stdout is empty (no success messages emitted by the service layer).
- With `set_debug(True)`, stderr includes both info and debug lines.
- Without either flag, stderr has no info or debug output.

### E2E — `tests/e2e/test_pull_cli.py`, `test_fetch_cli.py`

Typer's `CliRunner` mixes stdout and stderr by default (`mix_stderr=True`). For stream
routing tests, instantiate a runner with `mix_stderr=False` so stdout and stderr can be
asserted independently.

- `margot pull --verbose <uri>`: step-level info lines appear in stderr; pulled paths in stdout.
- `margot pull --debug <uri>`: info + debug lines in stderr; pulled paths in stdout.
- `margot pull <uri>` (no flags): stderr has no info/debug; stdout has pulled paths.
- Warning messages (force flags) appear in stderr regardless of verbosity.
- `margot --verbose pull <uri>` works identically to `margot pull --verbose <uri>`.
- `margot pull --debug <uri>` also emits verbose info (debug implies verbose).

### Fixture — `conftest.py`

Add both `capture_console` and `reset_console` as described above. Use `reset_console`
in any test that calls `set_verbose(True)` or `set_debug(True)`.
