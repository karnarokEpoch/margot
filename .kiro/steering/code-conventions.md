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

# wrong
from rich import print as rprint
rprint("[green]Pulled:[/green] path/to/file")
echo("Error: ...", err=True)
```

Rules:
- `success` → stdout (pipeable). `warning`, `info`, `debug`, `fatal` → stderr.
- `domain/` must not import `console` — it raises `ValueError`, the calling layer logs the outcome.
- `commands/` use `success`, `warning`, `fatal`. Never emit `info` or `debug` from a command directly.
- `services/` emit `info` at each significant step.
- `infra/` emit `debug` per I/O call.
- The one exception: `echo(f"margot {get_version()}")` in `global_options.py` — version output is not a log message.

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

### Running tests

```bash
uv run pytest
```
