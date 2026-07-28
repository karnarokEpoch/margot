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

## Testing

- **TDD is mandatory.** Write tests for the expected final behavior before or alongside implementation. Never write stub tests that just verify a `NotImplementedError` — test what the code *should* do. A failing test is correct and expected until the implementation catches up.

### Running tests

```bash
uv run pytest
```
