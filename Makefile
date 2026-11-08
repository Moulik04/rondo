# Rondo · European football analytics
# Every recipe runs in bash with -e -u -o pipefail, so a failing step fails the target.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV ?= uv
TORCH_EXTRA ?= cpu
NPM ?= npm

.PHONY: help setup data check lint format test test-real report export api web-dev web-build \
        gpu-bundle machines

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install Python deps (uv, locked) and web deps (npm ci)
	$(UV) sync --locked --extra $(TORCH_EXTRA)
	cd web && $(NPM) ci

data: ## Ingest provider data into data/ (built in Phase 1)
	@echo "make data: not built yet (Phase 1)" >&2; exit 1

check: ## Data quality checks on the local database (built in Phase 1)
	@echo "make check: not built yet (Phase 1)" >&2; exit 1

lint: ## ruff lint + format check
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .

format: ## Apply ruff formatting and safe fixes
	$(UV) run --locked ruff check --fix .
	$(UV) run --locked ruff format .

test: ## Unit and smoke tests on synthetic fixtures
	$(UV) run --locked pytest -m "not real"

test-real: ## The same tests against the full local data (built in Phase 1)
	@echo "make test-real: not built yet (Phase 1)" >&2; exit 1

report: ## Generate reports/ from data and run records (built in Phase 1)
	@echo "make report: not built yet (Phase 1)" >&2; exit 1

export: ## Write static JSON for the site under web/public/data/ (built in Phase 3)
	@echo "make export: not built yet (Phase 3)" >&2; exit 1

api: ## Run the local FastAPI app on http://127.0.0.1:8000
	$(UV) run --locked uvicorn rondo.api.app:app --reload --host 127.0.0.1 --port 8000

web-dev: ## Vite dev server
	cd web && $(NPM) run dev

web-build: ## Type-check and build the static site into web/dist/
	cd web && $(NPM) run build

gpu-bundle: ## Build a Bridges-2 bundle: make gpu-bundle MODEL=<track>/<name> SPLIT=<train|eval> (Phase 1)
	@echo "make gpu-bundle: not built yet (Phase 1)" >&2; exit 1

machines: ## Print the measured machine block
	$(UV) run --locked python -m rondo.core.machine
