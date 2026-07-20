.PHONY: test lint fmt check

test:
	uv run pytest

lint:
	uv run ruff check --no-fix src/ tests/

lint-fix:
	uv run ruff check src/ tests/

fmt:
	uv run ruff format --fix src/ tests/

check: lint test
