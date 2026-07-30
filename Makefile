SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV ?= uv
DENO := $(UV) run deno
DIST_DIR := $(CURDIR)/dist

.PHONY: help install format lint typecheck test check build docs-build docs-serve package

help: ## List development targets.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install locked Python, Deno, and documentation dependencies.
	$(UV) sync --locked
	$(DENO) install --frozen

format: ## Format Python and TypeScript sources.
	$(UV) run ruff format src tests
	$(DENO) task fmt

lint: ## Check formatting, source, workflows, and shell scripts.
	$(UV) run ruff format --check src tests
	$(UV) run ruff check
	$(DENO) task fmt:check
	$(DENO) task lint
	uvx --from actionlint-py==1.7.12.24 actionlint .github/workflows/*.yml
	shellcheck scripts/*.sh

typecheck: ## Type-check Python and TypeScript sources.
	$(UV) run ty check
	$(UV) run pyrefly check
	$(DENO) task check

test: ## Run Python and frontend tests.
	$(UV) run pytest
	$(DENO) task test

check: lint typecheck test ## Run the local quality gates.

build: ## Build the browser runtime into the Python package.
	$(DENO) task build

docs-build: ## Build the VitePress documentation.
	$(DENO) task docs:build

docs-serve: ## Serve documentation at http://127.0.0.1:4173/.
	GITHUB_ACTIONS=false $(DENO) task docs:dev

package: build ## Build and validate the wheel and source distribution.
	rm -rf "$(DIST_DIR)"
	$(UV) build --out-dir "$(DIST_DIR)"
	uvx twine check "$(DIST_DIR)"/*.whl "$(DIST_DIR)"/*.tar.gz
	mkdir -p "$(DIST_DIR)/from-sdist"
	$(UV) build --wheel "$(DIST_DIR)"/*.tar.gz --out-dir "$(DIST_DIR)/from-sdist"
	./scripts/verify-dist.sh
