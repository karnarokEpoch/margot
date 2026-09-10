.PHONY: help test lint lint-fix fmt check docs docs-serve docs-check

.DEFAULT_GOAL := help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-14s\033[0m %s\n", $$1, $$2}'

test:  ## Run pytest with coverage
	uv run pytest $(PYTEST_ARGS)

lint:  ## Run Ruff checks without auto-fixing
	uv run ruff check --no-fix src/ tests/

lint-fix:  ## Run Ruff checks with auto-fix
	uv run ruff check src/ tests/

fmt:  ## Format code with Ruff
	uv run ruff format --fix src/ tests/

check: lint test  ## Run lint followed by tests

docs:  ## Build the MkDocs site
	uv run --group docs mkdocs build

docs-serve:  ## Serve the MkDocs site locally with live reload
	uv run --group docs mkdocs serve

docs-check:  ## Strict MkDocs build (warnings as errors)
	uv run --group docs mkdocs build --strict
