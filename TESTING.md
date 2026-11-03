# margot — Testing Plan

All behavior documented in [docs/](https://karnarokepoch.github.io/margot/) and defined in the active sprint file must have test coverage.

---

## Stack

| Concern | Choice |
| --- | --- |
| Runner | pytest ≥ 8.0 |
| Parallelism | pytest-xdist ≥ 3.8.0 (`-n auto` default) |
| Mocking | pytest-mock (patches `OrasClient` at boundary) |
| Coverage | pytest-cov |
| CLI testing | Typer `CliRunner` |

Add to `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "ruff>=0.11.0",
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-mock>=3.14",
    "pytest-xdist>=3.8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-n auto --cov=margot --cov-report=term-missing --cov-fail-under=90"
```

Run tests serially for debugging with `uv run pytest -n 0`.

---

## Structure

```
tests/
├── conftest.py                  # shared fixtures: tmp dirs, fake metadata, mock OrasClient
├── unit/
│   ├── test_tags.py             # semver accept/reject matrix — this IS the spec for tags
│   ├── test_metadata.py         # parse valid + malformed margo.yaml
│   ├── test_credentials.py      # expiry logic (expired, near-expiry, no entry)
│   ├── test_config.py           # priority layering (flag > env > file)
│   └── validation/
│       ├── test_linkml_runner.py
│       └── test_error_formatter.py
├── integration/
│   ├── test_build.py            # rsync + sed substitutions, tarball contents
│   ├── test_push.py             # mock OrasClient, assert correct push params + media types
│   ├── test_pull.py
│   ├── test_fetch.py
│   └── test_verify.py           # valid + invalid margo.yaml, remote mock
└── e2e/
    └── test_cli.py              # CliRunner smoke tests: every command, exit codes, output
```

---

## Priorities

1. **`test_tags.py` first** — semver validation is a hard gate on every build/push. Define the accept/reject matrix before implementing `tags.py`. Valid: `1.0.0`, `1.3.0-simple.1`, `1.3.0+addon-mosquitto`. Invalid: `v1.0.0`, `1.0`, `latest`, empty string.
2. **Unit tests before integration** — `tags.py`, `metadata.py`, `credentials.py` are pure logic, no mocks needed.
3. **Mock `OrasClient` at the boundary** — integration tests never hit a live registry.
4. **E2E covers CLI surface** — exit codes, error messages, `--help` output.

---

## Test independence

Tests run in parallel via pytest-xdist by default. For this to work reliably:

- **No shared mutable state** — do not store test artifacts in module-level variables
  or global singletons; use fixtures for setup/teardown.
- **No terminal width assumptions** — terminal output is pinned to 120 columns in
  `tests/conftest.py` via the `COLUMNS` environment variable. Tests that assert on
  specific output substrings must account for this width.
