SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= pnpm
VP := $(PNPM) exec vp
DIST_DIR := $(CURDIR)/dist
PY_PACKAGE := packages/marimo-studio
PYTHON_PATHS := $(PY_PACKAGE) scripts
FORMAT_PATHS := README.md AGENTS.md .github apps development_docs docs examples packages skills package.json plugin.json pnpm-workspace.yaml tsconfig.json vite.config.ts
TYPECHECK_PATHS := apps/browser apps/docs/.vitepress apps/docs/scripts apps/e2e packages/presentation packages/protocol packages/runtime packages/studio packages/marimo-frontend/scripts packages/marimo-frontend/src vite.config.ts
DENO_PROVIDER_ROOTS := $(PY_PACKAGE)/src/marimo_studio/view_providers/_bundled/_deno $(PY_PACKAGE)/src/marimo_studio/view_providers/_bundled/deno_react $(PY_PACKAGE)/src/marimo_studio/view_providers/_bundled/deno_svelte
DENO_PROVIDER_LINT_SOURCES := $(shell find $(DENO_PROVIDER_ROOTS) -type f \( -name '*.ts' -o -name '*.tsx' \) ! -name '*.d.ts' | sort)

.PHONY: help setup format lint typecheck python-test frontend-test test check build
.PHONY: e2e e2e-ui docs-build docs-serve package
.PHONY: _anti-slop-check _architecture-check _provider-sources-check _examples-check
.PHONY: _prepare-frontend _frontend-ready _browser-install _browser-ready

help: ## List development targets.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Prepare dependencies, browser assets, and Chromium.
	$(UV) sync --locked --reinstall-package marimo-studio
	$(PNPM) install --frozen-lockfile
	$(MAKE) _prepare-frontend
	$(MAKE) build
	$(MAKE) _browser-install

_anti-slop-check:
	node --test --test-concurrency=1 tools/oxlint/anti-slop/test/*.test.ts tools/oxlint/anti-slop/test/compatibility/*.test.ts
	$(PNPM) exec tsc -p tools/oxlint/anti-slop/tsconfig.json --noEmit

format: ## Format Python and JavaScript sources.
	$(UV) run ruff format $(PYTHON_PATHS)
	$(VP) fmt $(FORMAT_PATHS)
	$(UV) run --frozen deno fmt $(DENO_PROVIDER_ROOTS)

_provider-sources-check:
	$(UV) run --frozen deno fmt --check $(DENO_PROVIDER_ROOTS)
	$(UV) run --frozen deno lint --rules-exclude=no-import-prefix $(DENO_PROVIDER_LINT_SOURCES)

_architecture-check:
	$(UV) run python scripts/check_python_architecture.py

lint: _frontend-ready _anti-slop-check _architecture-check _provider-sources-check ## Check formatting, source, workflows, and shell scripts.
	$(UV) run ruff format --check $(PYTHON_PATHS)
	$(UV) run ruff check $(PYTHON_PATHS)
	$(VP) fmt --check $(FORMAT_PATHS)
	$(VP) lint apps packages vite.config.ts
	uvx --from actionlint-py==1.7.12.24 actionlint .github/workflows/*.yml
	shellcheck scripts/*.sh

typecheck: _frontend-ready ## Type-check Python and TypeScript sources.
	$(UV) run ty check
	$(UV) run pyrefly check
	$(UV) run basedpyright --level error
	$(VP) check --no-fmt --no-lint $(TYPECHECK_PATHS)

python-test: ## Run the complete Python test profile for this environment.
	./scripts/python-test.sh --profile all

frontend-test: _frontend-ready ## Run JavaScript and TypeScript tests.
	$(VP) run -r test

test: python-test frontend-test ## Run Python and frontend tests.

_examples-check:
	$(UV) run python scripts/verify-example-artifacts.py

check: lint typecheck test _examples-check ## Run the local quality gates.

build: ## Build browser assets into the Python package.
	$(VP) run --filter @marimo-studio/browser build

_browser-install:
	$(PNPM) --filter @marimo-studio/e2e install-browser

e2e: _browser-ready build ## Test source and installed-package flows in Chromium.
	$(PNPM) --filter @marimo-studio/e2e e2e
	$(PNPM) --filter @marimo-studio/e2e e2e:providers
	$(PNPM) --filter @marimo-studio/e2e e2e:installed

e2e-ui: _browser-ready build ## Open the browser test runner.
	$(PNPM) --filter @marimo-studio/e2e e2e:ui

docs-build: ## Build the VitePress documentation.
	$(VP) run --filter @marimo-studio/docs build

docs-serve: ## Serve documentation at http://127.0.0.1:4173/.
	BASE_PATH= $(VP) run --filter @marimo-studio/docs dev

package: build ## Build and validate the wheel and source distribution.
	rm -rf "$(DIST_DIR)"
	$(UV) build --package marimo-studio --out-dir "$(DIST_DIR)"
	mkdir -p "$(DIST_DIR)/from-sdist"
	$(UV) build --wheel "$(DIST_DIR)"/*.tar.gz --out-dir "$(DIST_DIR)/from-sdist"
	$(UV) run --frozen --group release twine check \
		"$(DIST_DIR)"/*.whl \
		"$(DIST_DIR)"/*.tar.gz \
		"$(DIST_DIR)"/from-sdist/*.whl
	./scripts/verify-dist.sh

_prepare-frontend:
	$(PNPM) --filter @marimo-studio/marimo-frontend prepare:upstream

_frontend-ready:
	$(PNPM) --filter @marimo-studio/marimo-frontend check:upstream

_browser-ready:
	@$(PNPM) --filter @marimo-studio/e2e check-browser
