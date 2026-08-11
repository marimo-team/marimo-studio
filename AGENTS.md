# AGENTS.md

Marimo Studio adds authored view documents and an editor workspace inside a
Marimo process. Marimo retains ownership of notebook execution, sessions,
authentication, WebSockets, virtual files, and native routes.

## Commands

| Task                 | Command           |
| -------------------- | ----------------- |
| Install              | `make install`    |
| Format               | `make format`     |
| Lint                 | `make lint`       |
| Type-check           | `make typecheck`  |
| Test                 | `make test`       |
| Browser acceptance   | `make e2e`        |
| Browser test runner  | `make e2e-ui`     |
| Local gate           | `make check`      |
| Build browser assets | `make build`      |
| Build docs           | `make docs-build` |
| Serve docs           | `make docs-serve` |
| Build distributions  | `make package`    |

Python tooling runs through `uv`. Browser and documentation tooling runs
through the pnpm workspace, where Vite Plus owns formatting, linting,
TypeScript checks, tests, builds, and task execution.

## Architecture rules

- Marimo owns the process, auth, notebook execution, sessions, WebSockets,
  virtual files, and native routes.
- `_workspace` owns configuration and files, `_compat` owns private Marimo
  integration, `_server` owns Studio HTTP routes, and `_cli` adapts commands.
  `_composition.py` builds the adapter bundle behind `_capabilities.py` ports.
  `_workspace`, `_server`, and `_cli` import no concrete compatibility adapter.
  Private `marimo._*` imports stay in `_compat`. Ruff enforces these boundaries.
- `packages/protocol` owns browser records and performs no I/O.
  `packages/runtime` imports protocol and performs no Marimo, React, or browser
  I/O.
- `packages/presentation` owns the custom view document. `packages/studio`
  owns the editor workspace. `packages/marimo-frontend` contains unstable
  Marimo frontend imports.
- Studio source follows `app -> features -> shared`. Features import no app
  module, and shared primitives import no app or feature module.
- `apps/browser` composes package entry points. `apps/e2e` owns live browser
  acceptance. `apps/docs` owns VitePress while `docs/` owns authored pages.

## Sources of truth

Read contracts in this order:

1. `_compat/release.json` for the supported Marimo version and tag commit.
2. `_capabilities.py` for Studio-owned Python ports.
3. `packages/protocol` for browser records.
4. Runtime diagnostics and contract tests for observed behavior.
5. Contributor and user guides for workflows.

## Mutable owners

| State                      | Owner                                    | Release boundary                          |
| -------------------------- | ---------------------------------------- | ----------------------------------------- |
| Notebook services          | `NotebookScopeRegistry`                  | Marimo application lifespan               |
| Session replay             | `PrivateSessionReplay`                   | Final adapter handle                      |
| Document revision          | Presentation revision runtime            | Presentation handle disposal              |
| Projected output resources | Marimo frontend projected-output adapter | Final rendered owner                      |
| Save transformation        | Notebook source-transform extension      | Session detach or server adapter shutdown |

## Validation

- Run focused checks while working and `make check` before handoff.
- Run `make build` and `make e2e` after a change crosses Python, browser,
  document, or session boundaries.
- Keep tests with their owner. Use `apps/e2e` for behavior that crosses the
  native editor, kernel, filesystem, and preview documents.
- Build generated browser assets from workspace source and verify distribution
  contents with `make package`.
- Validate visible changes at desktop and narrow widths. Check console errors,
  failed requests, projections, controls, anywidgets, view switches, source
  saves, and external edits as the change requires.

## Task routing

| Task                                  | Guide                                              |
| ------------------------------------- | -------------------------------------------------- |
| General contribution                  | [Contributor guide](development_docs/README.md)    |
| Python architecture or Marimo upgrade | [Architecture](development_docs/architecture.md)   |
| Frontend facade or browser runtime    | [Frontend workspace](development_docs/frontend.md) |
| Live cross-boundary behavior          | `apps/e2e` and the browser acceptance commands     |
| Studio distribution or release        | [Releasing](development_docs/releasing.md)         |
