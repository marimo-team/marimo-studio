SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= pnpm
VP := $(PNPM) exec vp
DIST_DIR := $(CURDIR)/dist
PY_PACKAGE := packages/marimo-studio
FORMAT_PATHS := README.md AGENTS.md .github apps development_docs docs examples packages skills package.json pnpm-workspace.yaml tsconfig.json vite.config.ts
TYPECHECK_PATHS := apps/browser apps/docs/.vitepress apps/e2e packages/presentation packages/protocol packages/runtime packages/studio packages/marimo-frontend/src vite.config.ts

.PHONY: help install format lint typecheck test examples-check e2e e2e-ui check build docs-build docs-serve package prepare-frontend

help: ## List development targets.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install locked Python and JavaScript dependencies.
	$(UV) sync --locked
	$(PNPM) install --frozen-lockfile

format: ## Format Python and JavaScript sources.
	cd $(PY_PACKAGE) && $(UV) run --project ../.. ruff format .
	$(VP) fmt $(FORMAT_PATHS)

lint: prepare-frontend ## Check formatting, source, workflows, and shell scripts.
	cd $(PY_PACKAGE) && $(UV) run --project ../.. ruff format --check .
	cd $(PY_PACKAGE) && $(UV) run --project ../.. ruff check .
	$(VP) fmt --check $(FORMAT_PATHS)
	$(VP) lint apps packages vite.config.ts
	uvx --from actionlint-py==1.7.12.24 actionlint .github/workflows/*.yml
	shellcheck scripts/*.sh

typecheck: prepare-frontend ## Type-check Python and TypeScript sources.
	$(UV) run ty check
	$(UV) run pyrefly check
	$(VP) check --no-fmt --no-lint $(TYPECHECK_PATHS)

test: ## Run Python and browser-runtime tests.
	$(UV) run pytest
	$(VP) run -r test

examples-check: build ## Validate every example notebook and Studio view.
	$(UV) run marimo check examples/analysis.py examples/nga_collection.py
	$(UV) run marimo-studio check examples/analysis.py --runtime
	$(UV) run marimo-studio check examples/nga_collection.py

e2e: build ## Test Studio in Chromium with a live Marimo kernel.
	$(PNPM) --filter @marimo-studio/e2e e2e

e2e-ui: build ## Open the browser test runner.
	$(PNPM) --filter @marimo-studio/e2e e2e:ui

check: lint typecheck test examples-check ## Run the local quality gates.

build: ## Build browser assets into the Python package.
	$(VP) run --filter @marimo-studio/browser build

docs-build: ## Build the VitePress documentation.
	$(VP) run --filter @marimo-studio/docs build

docs-serve: ## Serve documentation at http://127.0.0.1:4173/.
	BASE_PATH= $(VP) run --filter @marimo-studio/docs dev

package: build ## Build and validate the wheel and source distribution.
	rm -rf "$(DIST_DIR)"
	$(UV) build --package marimo-studio --out-dir "$(DIST_DIR)"
	uvx twine check "$(DIST_DIR)"/*.whl "$(DIST_DIR)"/*.tar.gz
	mkdir -p "$(DIST_DIR)/from-sdist"
	$(UV) build --wheel "$(DIST_DIR)"/*.tar.gz --out-dir "$(DIST_DIR)/from-sdist"
	./scripts/verify-dist.sh

prepare-frontend:
	$(PNPM) --filter @marimo-studio/marimo-frontend prepare:upstream
