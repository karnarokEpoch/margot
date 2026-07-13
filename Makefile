.PHONY: test lint fmt check

test:
	uv run pytest

lint:
	uv run ruff check src/ tests/

fmt:
	uv run ruff format src/ tests/

check:
	uv run ruff check --no-fix src/ tests/
