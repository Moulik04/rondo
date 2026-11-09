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

data: ## Fetch StatsBomb (pinned) and build data/parquet/ + data/rondo.duckdb, timed
	mkdir -p data/logs
	/usr/bin/time -l $(UV) run --locked python -W ignore -m rondo.core.build 2>&1 | tee data/logs/make_data.log

check: ## Data-quality checks on data/parquet/; writes reports/data_quality.md, fails on FAIL
	$(UV) run --locked python -W ignore -m rondo.core.checks

lint: ## ruff lint + format check
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .

format: ## Apply ruff formatting and safe fixes
	$(UV) run --locked ruff check --fix .
	$(UV) run --locked ruff format .

test: ## Unit, data and smoke tests on synthetic fixtures
	$(UV) run --locked pytest

test-real: ## The same data tests against the full local data (needs make data)
	$(UV) run --locked pytest --real tests/core

report: ## Generate reports/statsbomb_summary.md and reports/gpu_ledger.md
	$(UV) run --locked python -W ignore -m rondo.core.report

export: ## Write static JSON for the site under web/public/data/ (built in Phase 3)
	@echo "make export: not built yet (Phase 3)" >&2; exit 1

api: ## Run the local FastAPI app on http://127.0.0.1:8000
	$(UV) run --locked uvicorn rondo.api.app:app --reload --host 127.0.0.1 --port 8000

web-dev: ## Vite dev server
	cd web && $(NPM) run dev

web-build: ## Type-check and build the static site into web/dist/
	cd web && $(NPM) run build

gpu-bundle: ## Bridges-2 bundle: make gpu-bundle MODEL=<track>/<name> SPLIT=<train|eval>
	@test -n "$(MODEL)" -a -n "$(SPLIT)" || { echo "usage: make gpu-bundle MODEL=<track>/<name> SPLIT=<train|eval>" >&2; exit 2; }
	$(UV) run --locked python -m rondo.core.bundle --model $(MODEL) --split $(SPLIT)

machines: ## Print the measured machine block (OUT=<file.md> writes it into that file)
	$(UV) run --locked python -m rondo.core.machine $(if $(OUT),--write $(OUT),)
