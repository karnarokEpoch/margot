.PHONY: test lint fmt check docs docs-serve docs-check

test:
	uv run pytest

lint:
	uv run ruff check --no-fix src/ tests/

lint-fix:
	uv run ruff check src/ tests/

fmt:
	uv run ruff format --fix src/ tests/

check: lint test

docs:
	uv run --group docs mkdocs build

docs-serve:
	uv run --group docs mkdocs serve

docs-check:
	uv run --group docs mkdocs build --strict
