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
DENO_PROVIDER_ROOTS := $(PY_PACKAGE)/src/marimo_studio/view_providers/_bundled/deno_obsnotebook $(PY_PACKAGE)/src/marimo_studio/view_providers/_bundled/_deno $(PY_PACKAGE)/src/marimo_studio/view_providers/_bundled/deno_react $(PY_PACKAGE)/src/marimo_studio/view_providers/_bundled/deno_svelte
DENO_PROVIDER_LINT_SOURCES := $(shell find $(DENO_PROVIDER_ROOTS) -type f \( -name '*.ts' -o -name '*.tsx' \) ! -name '*.d.ts' | sort)
# Portless binds its default proxy port 443 through sudo. Without a terminal,
# reuse a proxy already answering there, or start the unprivileged proxy.
PORTLESS_ENV = $(shell [ -t 0 ] || { command -v nc >/dev/null && nc -z 127.0.0.1 443 2>/dev/null; } || echo PORTLESS_PORT=1355)
PYTHON_BUILD_CONSTRAINTS = $(UV) export --frozen --package marimo-studio --only-group marimo-studio-build --no-emit-workspace --no-annotate --no-header

.PHONY: help setup format lint typecheck python-test frontend-test test check build
.PHONY: e2e e2e-ui docs-examples docs-thumbnails docs-build docs-serve docs-preview package
.PHONY: _anti-slop-check _architecture-check _provider-sources-check _workflow-check
.PHONY: _prepare-frontend _frontend-ready _browser-install _browser-ready
.PHONY: _prepare-browser-tests
.PHONY: _package-build

help: ## List development targets.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Prepare dependencies, browser assets, and Chromium.
	$(UV) sync --locked --reinstall-package marimo-studio
	$(PNPM) install --frozen-lockfile
	$(MAKE) _prepare-frontend
	$(MAKE) _prepare-browser-tests
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

_workflow-check:
	./scripts/check-workflow-results.test.sh
	node --test .github/actions/pr-validation/*.test.mjs

lint: _frontend-ready _anti-slop-check _architecture-check _provider-sources-check _workflow-check ## Check formatting, source, workflows, and shell scripts.
	$(UV) run ruff format --check $(PYTHON_PATHS)
	$(UV) run ruff check $(PYTHON_PATHS)
	$(VP) fmt --check $(FORMAT_PATHS)
	$(VP) lint apps packages vite.config.ts
	uvx --from actionlint-py==1.7.12.24 actionlint \
		-ignore 'unexpected key "queue" for "concurrency" section' \
		.github/workflows/*.yml
	shellcheck scripts/*.sh .github/actions/pr-validation/*.sh

typecheck: _frontend-ready ## Type-check Python and TypeScript sources.
	$(UV) run ty check
	$(UV) run pyrefly check
	$(UV) run basedpyright --level error
	$(VP) check --no-fmt --no-lint $(TYPECHECK_PATHS)
	$(PNPM) --filter @marimo-studio/e2e typecheck

python-test: ## Run the complete Python test profile for this environment.
	./scripts/python-test.sh --profile all --parallel

frontend-test: _frontend-ready ## Run JavaScript and TypeScript tests.
	VITEST_MAX_WORKERS=$${VITEST_MAX_WORKERS:-2} $(VP) run -r test

test: python-test frontend-test ## Run Python and frontend tests.

check: lint typecheck test ## Run the local quality gates.

build: ## Build browser assets into the Python package.
	$(VP) run --filter @marimo-studio/browser build

_browser-install:
	$(PNPM) --filter @marimo-studio/e2e install-browser

_prepare-browser-tests: _frontend-ready
	$(PNPM) --filter @marimo-studio/e2e exec node scripts/prepare-pyodide.ts

e2e: _browser-ready build _prepare-browser-tests ## Test source and installed-package flows in Chromium.
	$(PNPM) --filter @marimo-studio/e2e e2e
	$(PNPM) --filter @marimo-studio/e2e e2e:providers
	$(PNPM) --filter @marimo-studio/e2e e2e:installed

e2e-ui: _browser-ready build _prepare-browser-tests ## Open the browser test runner.
	$(PNPM) --filter @marimo-studio/e2e e2e:ui

docs-examples: _frontend-ready build ## Export examples for the documentation site.
	$(VP) run --filter @marimo-studio/docs examples:build

docs-thumbnails: _browser-ready ## Capture example thumbnails and landing posters from exported views.
	@test -d apps/docs/public/examples || $(MAKE) docs-examples
	$(VP) run --filter @marimo-studio/docs thumbnails

docs-build: _frontend-ready build ## Build the VitePress documentation.
	$(VP) run --filter @marimo-studio/docs build

docs-serve: _frontend-ready build ## Serve documentation through Portless.
	$(PORTLESS_ENV) BASE_PATH= $(VP) run --filter @marimo-studio/docs dev

docs-preview: _frontend-ready ## Preview built documentation through Portless.
	$(PORTLESS_ENV) $(VP) run --filter @marimo-studio/docs preview

package: _package-build ## Build and validate the wheel and source distribution.
	./scripts/verify-installed-wheel.sh "$(DIST_DIR)"

_package-build: build
	rm -rf "$(DIST_DIR)"
	$(UV) build --package marimo-studio \
		--build-constraints <($(PYTHON_BUILD_CONSTRAINTS)) --require-hashes \
		--out-dir "$(DIST_DIR)"
	mkdir -p "$(DIST_DIR)/from-sdist"
	$(UV) build --wheel "$(DIST_DIR)"/*.tar.gz \
		--build-constraints <($(PYTHON_BUILD_CONSTRAINTS)) --require-hashes \
		--out-dir "$(DIST_DIR)/from-sdist"
	$(UV) run --frozen --group release twine check \
		"$(DIST_DIR)"/*.whl \
		"$(DIST_DIR)"/*.tar.gz \
		"$(DIST_DIR)"/from-sdist/*.whl
	./scripts/verify-dist.sh
	$(UV) run --frozen python scripts/write-dist-checksums.py "$(DIST_DIR)"

_prepare-frontend:
	$(PNPM) --filter @marimo-studio/marimo-frontend prepare:upstream

_frontend-ready:
	$(PNPM) --filter @marimo-studio/marimo-frontend check:upstream

_browser-ready:
	@$(PNPM) --filter @marimo-studio/e2e check-browser
