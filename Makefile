.PHONY: setup lint typecheck test audit check

setup:
	uv sync --locked --all-packages

lint:
	uv run --locked --all-packages ruff check .
	uv run --locked --all-packages ruff format --check .

typecheck:
	uv run --locked --all-packages mypy apps packages

test:
	uv run --locked --all-packages pytest

audit:
	uv run --locked --all-packages bandit -c pyproject.toml -r apps packages && uv run --locked --all-packages pip-audit --skip-editable
	uv run --locked --all-packages go run github.com/zricethezav/gitleaks/v8@v8.30.1 dir --redact .

check: lint typecheck test audit
