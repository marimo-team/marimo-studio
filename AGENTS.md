# AGENTS.md

Marimo owns notebook execution, sessions, authentication, and native routes.
Marimo Studio adds custom view documents and an editor workspace inside that
process.

## Commands

| Task                 | Command           |
| -------------------- | ----------------- |
| Install              | `make install`    |
| Format               | `make format`     |
| Lint                 | `make lint`       |
| Type-check           | `make typecheck`  |
| Test                 | `make test`       |
| Local gate           | `make check`      |
| Build browser assets | `make build`      |
| Build docs           | `make docs-build` |
| Serve docs           | `make docs-serve` |
| Build distributions  | `make package`    |

Python tooling runs through `uv`. Browser and documentation tooling runs
through the pnpm workspace. Vite Plus provides formatting, linting, TypeScript
checks, tests, builds, and workspace task execution.

Run focused checks while working and `make check` before handoff. Run
`make build` and browser acceptance after a change crosses the Python and
TypeScript boundary.

## Architecture

- **Marimo is the host.** The `marimo.server.asgi.middleware` and
  `marimo.kernel.lifespan` entry points load Studio into Marimo. Marimo keeps
  ownership of the ASGI lifecycle, sessions, kernels, WebSockets, virtual
  files, authentication, and native APIs.
- **`packages/marimo-studio` is the Python distribution.** `_workspace` owns
  configuration, views, bindings, checks, and authored files. `_server` owns
  Studio routes and HTTP translation. `_cli` adapts Click commands to
  application services. `_compat` isolates private Marimo Python APIs.
- **`packages/protocol` owns browser wire records.** Zod schemas validate
  messages and server responses and provide their inferred TypeScript types.
  The package performs no network, filesystem, DOM, or window I/O.
- **Each browser document has one package.** `packages/presentation` owns the
  custom view and its React runtime. `packages/studio` owns panes, source
  editors, view management, and preview coordination.
  `packages/marimo-frontend` isolates Marimo's unstable frontend API.
- **Apps compose packages.** `apps/browser` owns the Vite build and packaged
  asset names. `apps/docs` owns VitePress while authored pages remain in
  `docs/`.

See [Architecture](development_docs/architecture.md) for the runtime and
session lifecycle.

## Dependency direction

- `marimo_studio._workspace` imports no compatibility adapter. It accepts
  `NotebookInspector` and `RuntimeProber` ports where Marimo data is required.
- `marimo_studio._compat` may depend on workspace rules and Studio-owned
  records. Application services, server composition, and plugin entry points
  compose the two slices.
- `marimo_studio._cli` imports no compatibility adapter. Commands pass Python
  values to workspace targets and application services, then format results.
- Production imports beginning with `marimo._` stay in
  `packages/marimo-studio/src/marimo_studio/_compat`. Compatibility tests may
  import private Marimo types to exercise that boundary.
- `packages/protocol` performs no I/O and imports no workspace package.
- `packages/studio` imports protocol, never presentation or Marimo frontend
  modules.
- `packages/presentation` imports protocol and named Marimo adapter exports.
- Imports from `@marimo-team/frontend/unstable_internal` and Marimo's `@/`
  alias stay in `packages/marimo-frontend`.
- `apps/browser` composes build entry points. Browser behavior stays with the
  package that owns its document.

Root `vite.config.ts` enforces browser import boundaries. Ruff enforces the
Python compatibility boundary.

## Invariants

- Notebook authors keep ordinary Marimo cells and can expose several views.
- `marimo edit` embeds the native editor and shares its session with custom
  previews. `marimo run` creates an isolated Marimo session per browser.
- View switches and shell refreshes preserve the preview runtime, WebSocket,
  kernel, output plugins, and widget models.
- `<marimo-cell>` uses Marimo's output and widget clients. `mo-value` reads
  selectors permitted by the active view through the kernel queue.
- Runtime configuration validates cell identity against the active notebook.
  Missing projections publish structured diagnostics while healthy hosts keep
  rendering.
- HTML, CSS, runtime configuration, and view selection commit at one
  presentation revision. A failed refresh keeps the last valid shell.
- Support routes honor the parent ASGI mount and Marimo `base_url`. Native
  authentication and unrelated Marimo routes pass through unchanged.
- The browser build preserves `runtime.js`, `dev-reload.js`, `studio.js`,
  `runtime.css`, `studio.css`, and `build-meta.json` for the Python package.
- PEP 723 edits preserve notebook bytes outside the managed metadata block.
  Source saves use content revisions and atomic replacement.

## Repository conventions

- Add JavaScript dependencies to the package that imports them. Reuse shared
  versions through `catalog:` and internal packages through `workspace:*`.
- Use the root Vite Plus configuration for formatting, linting, and TypeScript
  checks. Add package overrides there when a dependency boundary requires one.
- Keep tests with their owner. Protocol tests exercise schemas and envelopes.
  Presentation and Studio tests protect state and lifecycle contracts. Python
  tests protect commands, ASGI behavior, configuration, sessions, and package
  contents.
- Keep generated assets under
  `packages/marimo-studio/src/marimo_studio/_static/` untracked. Build them from
  workspace source and verify distribution contents with `make package`.
- Validate visible changes in the running Studio document. Cover desktop and
  narrow layouts, console errors, failed requests, projections, controls,
  anywidgets, view switches, source saves, and external edits.
- Keep comments for lifecycle, compatibility, serialization, and failure
  constraints. Remove comments that narrate ordinary code or the change itself.

## Contributor guides

- [Architecture](development_docs/architecture.md)
- [Frontend workspace](development_docs/frontend.md)
- [Releasing](development_docs/releasing.md)
