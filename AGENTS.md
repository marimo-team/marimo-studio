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
  `_workspace` and `_cli` import no compatibility adapter. Private `marimo._*`
  imports stay in `_compat`. Ruff enforces these boundaries.
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

## Contributor guides

- [Contributor guide](development_docs/README.md)
- [Architecture](development_docs/architecture.md)
- [Frontend workspace](development_docs/frontend.md)
- [Releasing](development_docs/releasing.md)
