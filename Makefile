.PHONY: setup lint typecheck test test-models test-integration db-up db-down infra-up infra-down telemetry-up telemetry-down migrate audit check local-run local-stop dev-token

TENANT ?= demo
SUBJECT ?= alice
TTL ?= 3600

setup:
	uv sync --locked --all-packages

local-run:
	bash scripts/local_run.sh

local-stop:
	docker compose --profile infra --profile telemetry --profile app down

dev-token:
	@docker compose --profile infra --profile telemetry --profile app run --rm --no-deps -T dev-issuer python /usr/local/lib/dev_issuer.py mint --tenant $(TENANT) --user $(SUBJECT) --ttl $(TTL)

lint:
	uv run --locked --all-packages ruff check .
	uv run --locked --all-packages ruff format --check .

typecheck:
	uv run --locked --all-packages mypy apps packages

test:
	uv run --locked --all-packages pytest

test-models:
	uv run --locked --all-packages pytest -m models --no-cov

test-integration:
	uv run --locked --all-packages pytest -m integration --no-cov

infra-up:
	docker compose --profile infra up -d
	bash scripts/smoke_infra.sh

infra-down:
	docker compose --profile infra down

telemetry-up:
	docker compose --profile telemetry up -d --wait --wait-timeout 120

telemetry-down:
	docker compose --profile telemetry down

db-up: infra-up

db-down: infra-down

migrate:
	uv run --locked --all-packages alembic upgrade head

audit:
	uv run --locked --all-packages bandit -c pyproject.toml -r apps packages && uv run --locked --all-packages pip-audit --skip-editable
	uv run --locked --all-packages go run github.com/zricethezav/gitleaks/v8@v8.30.1 dir --redact .

check: lint typecheck test audit
