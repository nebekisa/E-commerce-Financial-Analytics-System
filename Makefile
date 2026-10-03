.PHONY: help install test lint format check run clean

help:
	@echo "Targets:"
	@echo "  install   Install dependencies"
	@echo "  test      Run the test suite"
	@echo "  lint      Run ruff check and mypy"
	@echo "  format    Run ruff format"
	@echo "  check     Run lint + format --check + tests"
	@echo "  run       Run the CLI on the golden dataset"
	@echo "  clean     Remove caches and build artifacts"

install:
	pip install -r requirements-dev.txt

test:
	pytest tests/ -v

lint:
	ruff check .
	mypy config src

format:
	ruff format .
	ruff check . --fix

check: lint
	ruff format --check .
	pytest tests/ -q

run:
	python -m src.cli \
		--shopify tests/fixtures/golden_shopify.csv \
		--meta tests/fixtures/golden_meta.csv \
		--database data/processed/smoke.duckdb \
		--log-level WARNING

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true