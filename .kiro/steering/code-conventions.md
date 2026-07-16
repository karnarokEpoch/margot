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

## Testing

- **TDD is mandatory.** Write tests for the expected final behavior before or alongside implementation. Never write stub tests that just verify a `NotImplementedError` — test what the code *should* do. A failing test is correct and expected until the implementation catches up.

### Running tests

```bash
uv run pytest
```
