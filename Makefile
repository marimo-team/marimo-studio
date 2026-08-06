SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= pnpm
DIST_DIR := $(CURDIR)/dist
PY_PACKAGE := packages/marimo-studio

.PHONY: help install format lint typecheck test e2e e2e-ui check build docs-build docs-serve package

help: ## List development targets.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install locked Python and JavaScript dependencies.
	$(UV) sync --locked
	$(PNPM) install --frozen-lockfile

format: ## Format Python and JavaScript sources.
	cd $(PY_PACKAGE) && $(UV) run --project ../.. ruff format .
	$(PNPM) format

lint: ## Check formatting, source, workflows, and shell scripts.
	cd $(PY_PACKAGE) && $(UV) run --project ../.. ruff format --check .
	cd $(PY_PACKAGE) && $(UV) run --project ../.. ruff check .
	$(PNPM) format:check
	$(PNPM) lint
	uvx --from actionlint-py==1.7.12.24 actionlint .github/workflows/*.yml
	shellcheck scripts/*.sh

typecheck: ## Type-check Python and TypeScript sources.
	$(UV) run ty check
	$(UV) run pyrefly check
	$(PNPM) typecheck

test: ## Run Python and browser-runtime tests.
	$(UV) run pytest
	$(PNPM) test

e2e: ## Test Studio in Chromium with a live Marimo kernel.
	$(PNPM) e2e

e2e-ui: ## Open the browser test runner.
	$(PNPM) e2e:ui

check: lint typecheck test ## Run the local quality gates.

build: ## Build browser assets into the Python package.
	$(PNPM) build

docs-build: ## Build the VitePress documentation.
	$(PNPM) docs:build

docs-serve: ## Serve documentation at http://127.0.0.1:4173/.
	BASE_PATH= $(PNPM) docs:dev

package: build ## Build and validate the wheel and source distribution.
	rm -rf "$(DIST_DIR)"
	$(UV) build --package marimo-studio --out-dir "$(DIST_DIR)"
	uvx twine check "$(DIST_DIR)"/*.whl "$(DIST_DIR)"/*.tar.gz
	mkdir -p "$(DIST_DIR)/from-sdist"
	$(UV) build --wheel "$(DIST_DIR)"/*.tar.gz --out-dir "$(DIST_DIR)/from-sdist"
	./scripts/verify-dist.sh
