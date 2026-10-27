---
inclusion: manual
---

# Code Conventions

## Canonical OCI URI example

Use `public.ecr.aws/g2n4p2m7/margo:1.0.0` in all docstrings, help text, and documentation.
Never use project- or customer-specific refs (e.g. `belden-margo`).

## TODO format

Always write `# TODO(kiro): ...` — required by ruff TD002. Never bare `# TODO:`.

## Imports

Always use selective imports. Never import a module globally when only specific names are needed.

```python
# correct
from pytest import fixture, raises

# wrong
import pytest
```

Ruff PT013 (which would enforce `import pytest`) is disabled — selective imports apply to pytest too.
But it's also the same for typer, or others pythonic modules.

**Exemptions.** This rule applies to `src/` application code only. Test modules under
`tests/` may use plain `import X` for stdlib namespaces. `src/margot/console.py` is the
**sole** `import sys` exception in `src/` — it owns all access to `sys.stdin`, `sys.stdout`,
and `sys.stderr`. These are evaluated at call time so test runners can swap the streams at
runtime; a `from sys import stdout` would bind the stream object at import time and prevent
test stream capture. All stdin/stdout/stderr access — whether for console output or input —
routes through `console.py` functions (`_get_stdout()`, `_get_stderr()`, `read_stdin()`).

## Output / terminal output

All terminal output goes through `margot.console` — never use `rprint`, `echo`, or `print` directly in commands, services, or infra.

```python
# correct
import margot.console as console
console.success("Pulled: path/to/file")
console.warning("--force is active. Safety checks bypassed.")
console.info("Manifest fetched.")      # only shown with --verbose or --debug
console.debug(f"GET manifest: {uri}")  # only shown with --debug
console.fatal("Invalid URI.")          # prints error and raises Exit(1)
console.finding(escaped_line, "ERROR")  # print a validation finding with severity color
console.section("Schema A (Margo spec)")  # print a blue section separator
console.verdict("Schema A (Margo spec)", "PASS", "no findings")  # print a verdict with outcome coloring

# wrong
from rich import print as rprint
rprint("[green]Pulled:[/green] path/to/file")
echo("Error: ...", err=True)
```

Rules:
- `success` → stdout (pipeable). `warning`, `info`, `debug`, `fatal`, `finding`, `section`, `verdict` → stderr (except `verdict` → stdout).
- `domain/` must not import `console` — it raises `ValueError`, the calling layer logs the outcome.
- `commands/` use `success`, `warning`, `fatal`, `verdict`. Never emit `info` or `debug` from a command directly.
  - `finding(text, severity)` is for rendering validation findings with color matching severity (ERROR/WARNING/INFO) to stderr.
  - `section(label)` is for rendering blue section separators in validation output to stderr.
  - `verdict(label, outcome, detail)` is for rendering validation verdict lines (Schema A/B summaries) with outcome-aware coloring (PASS→green, FAIL→red, advisory→orange3) to stdout. Label renders white, outcome in color, detail plain.
- `services/` emit `info` at each significant step.
- `infra/` emit `debug` per I/O call.
- The one exception: `echo(f"margot {get_version()}")` in `global_options.py` — version output is not a log message.

## Exit codes

Every command failure exits with one of five codes. `docs/exit-codes.md` is the public
contract; this section is the rule for writing code and tests against it.

| Code | Meaning | Use for |
|---|---|---|
| `0` | Success | The command completed. |
| `1` | Generic / unexpected failure | An uncategorized exception (`Verify failed: …`, `Push failed: …`). Never a default for a known failure. |
| `2` | Usage error | Invalid flag value or incompatible flag combination, detected before any work (`invalid --type`, mutually exclusive flags, missing required flag). |
| `3` | Validation / semantic input failure | Malformed or invalid URI, descriptor, version, package selection, or local build output; missing `margo.yaml` or descriptor; schema validation failure. |
| `4` | Remote / authentication failure | Registry access, credential expiry or rejection, authentication, permission. |

**In code.** Pass the code explicitly: `console.fatal(msg, code=3)`. Do not rely on the
`code=1` default for a failure you can categorize. A `ValueError` from `domain/` or
`services/` is a `3`; an OCI/registry/auth error is a `4`; the final `except Exception`
fallback in a command is the only `1`. Codes are bare integers today — no shared constant.

**In tests.** The number in a test's name, docstring and comments must be the number it
asserts, and that number must be the category above for the situation under test.

```python
# correct — name, docstring and assertion agree, and 3 is the documented code for an invalid descriptor
def test_invalid_descriptor_exits_3(...) -> None:
    """Should exit 3 when the descriptor fails Schema A."""
    assert result.exit_code == 3

# wrong — "1" is the pre-taxonomy convention; the assertion says 3
def test_invalid_descriptor_exits_1(...) -> None:
    """Should exit 1 when the descriptor fails Schema A."""
    assert result.exit_code == 3
```

Rules:
- Name tests `…_exits_<code>` when the exit code is the point of the test; keep the docstring
  (`Should exit <code> …`) in sync.
- Never write "exits 1" for a known, categorized failure. `1` appears in a test only for an
  unexpected exception path.
- When changing a command's exit code, update in the same change: the code, the tests'
  names, docstrings and assertions, `docs/exit-codes.md`, and the command's page under
  `docs/commands/`.
- With `--json`, the same code is carried in the stderr envelope
  `{"error": true, "code": <int>, "message": "..."}`; the envelope `code` must equal the exit code.

## Overriding methods on a third-party base class

When a class in `infra/` subclasses a third-party library class (e.g.
`OrasClient(oras.client.OrasClient)`), an overridden method's signature must accept a
**strict superset** of what the base class method accepts — same or wider parameter
types, same or more optional parameters with defaults, never a narrowed type and never a
dropped parameter. This holds even when every call site in margot's own code only ever
uses the narrower form.

**Why:** the base class's own internals can call the overridden method back on `self`
polymorphically, with arguments margot's call sites never produce. `oras.provider.Registry
.pull()` calls `self.get_manifest(container, allowed_media_type)` and
`self.download_blob(container, ...)` internally with an already-built `Container` object
and extra positional args — not the plain URI string margot's own services pass in. An
override typed as `get_manifest(self, uri: str)` accepts margot's own calls fine but
raises `TypeError` the moment `super().pull()` dispatches back into it. This is a Liskov
Substitution Principle violation: a subclass must be substitutable for its base class from
the point of view of *any* caller, including the base class's own methods calling back
into `self`. See `src/margot/infra/oci.py` `get_manifest()` / `download_blob()` for the
fixed shape — signature widened to `container: str | Container, allowed_media_type=None,
validation_schema=None` (matching the base exactly), with the narrowing handled *inside*
the method body via `isinstance` checks, not in the signature.

```python
# wrong — narrows the base class contract
class OrasClient(OrasClientLib):
    def get_manifest(self, uri: str) -> dict[str, Any]:
        return super().get_manifest(uri)

# correct — superset signature, normalize internally
class OrasClient(OrasClientLib):
    def get_manifest(
        self,
        container: str | Container,
        allowed_media_type: list | None = None,
        validation_schema: dict | None = None,
    ) -> dict[str, Any]:
        if isinstance(container, str):
            container = self.get_container(container)
        return super().get_manifest(container, allowed_media_type, validation_schema)
```

Checklist before narrowing or simplifying an override:

- Read the base class's actual signature (`inspect.signature(Base.method)` or the source)
  before assuming margot's own call site is the only caller.
- Accept the union type and normalize inside the method body — don't reject the base
  type to keep the override "simple."
- Add a regression test that calls the override the way the *base class* calls it
  internally (polymorphic dispatch via another base method, e.g. `super().pull()`), not
  only the way margot's own services call it. That call path is what a signature-narrowing
  bug hides behind.

This is distinct from the `commands/` → `services/` → `domain/` + `infra/` layering rule
(module dependency direction) — this rule is about inheritance contracts when `infra/`
wraps a third-party class.

## Testing

- **TDD is mandatory.** Write tests for the expected final behavior before or alongside implementation. Never write stub tests that just verify a `NotImplementedError` — test what the code *should* do. A failing test is correct and expected until the implementation catches up.
- **Exit-code tests follow the taxonomy.** Any test that asserts `exit_code` must use the category from the "Exit codes" section above, and its name/docstring must state that same number.

### Running tests

```bash
uv run pytest
```
