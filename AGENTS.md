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
| Browser acceptance   | `make e2e`        |
| Browser test runner  | `make e2e-ui`     |
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
  application services. `export.py` packages one resolved view for a static
  host. `_compat` isolates private Marimo Python APIs.
- **`packages/protocol` owns browser wire records.** Zod schemas validate
  messages and server responses and provide their inferred TypeScript types.
  The package performs no network, filesystem, DOM, or window I/O.
- **`packages/runtime` owns the adapter contract.** Runtime definitions
  validate provider data and return a document-scoped session.
- **Each browser document has one package.** `packages/presentation` owns the
  custom view and its React runtime. `packages/studio` owns panes, source
  editors, view management, preview coordination, and cross-runtime native
  control sync. Its `app/` layer constructs the root and services, `features/`
  owns each user workflow, and `shared/` contains cross-feature primitives.
  `packages/marimo-frontend` isolates Marimo's unstable frontend API.
- **Apps compose packages.** `apps/browser` owns the Vite build and packaged
  asset names. `apps/docs` owns VitePress while authored pages remain in
  `docs/`. `apps/e2e` drives a copied notebook through a live `marimo edit`
  process.

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
- `packages/runtime` imports protocol and has no Marimo, React, or browser I/O
  dependency.
- `packages/studio` imports protocol, never presentation or Marimo frontend
  modules.
- Inside `packages/studio`, `main.tsx` enters `app/`. `navigation/` and
  `workspace/` compose sibling feature slices through typed controllers.
  Feature dependencies stay acyclic and may point to `shared/`. Shared
  primitives import no app or feature modules.
- `packages/presentation` imports protocol and named Marimo adapter exports.
- Imports from `@marimo-team/frontend/unstable_internal` and Marimo's `@/`
  alias stay in `packages/marimo-frontend`.
- `apps/browser` composes build entry points. Browser behavior stays with the
  package that owns its document.

Root `vite.config.ts` enforces browser import boundaries. Ruff enforces the
Python compatibility boundary.

## Invariants

- Notebook authors keep ordinary Marimo cells and can expose several views.
- New views contain `index.html` and `app.css`. Relative modules, images,
  fonts, and nested assets resolve from the named view directory.
- `_marimo-studio`, `@file`, `public`, and `public-files-sw.js` remain owned by
  Studio or Marimo beneath each view URL. Static export rejects destination
  collisions before copying authored assets.
- `marimo edit` embeds the native editor and shares its session with custom
  previews. `marimo run` creates an isolated Marimo session per browser.
- View switches and shell refreshes preserve prepared adapters, output
  plugins, and widget models. Runtime selection reveals an existing preview
  frame. A changed execution instance reloads its owning document.
- `<marimo-cell>` uses Marimo's output and widget clients. `mo-value` reads
  selectors permitted by the active view through the adapter's value reader.
- Server previews use Marimo sessions. WebAssembly previews run the derived
  notebook in a background Pyodide worker. Both use the shared presentation
  renderer.
- Static exports package one selected view with that same WebAssembly runtime.
  The bundle uses relative URLs and preserves the notebook's `public/` files.
- The default Studio mode places the notebook beside the preview. Toolbar view
  choices return to that mode. Links inside authored views preserve the active
  mode.
- Studio synchronizes JSON-compatible native `mo.ui` values between the edit
  kernel and a WebAssembly preview. Semantic cell references translate runtime
  cell IDs. Each cell must construct the same native controls in the same order
  in both runtimes. Anywidget comm state remains scoped to its originating
  runtime.
- Notebook query parameters synchronize through each adapter's kernel queue.
  Runtime selection and Marimo transport parameters stay outside notebook
  query state.
- Runtime configuration validates cell identity against the active notebook.
  Missing projections publish structured diagnostics while healthy hosts keep
  rendering.
- HTML, runtime configuration, and view selection commit at one presentation
  revision. CSS refreshes in place. Other view assets use their native browser
  URLs, and a saved asset reloads a scripted document. A failed shell refresh
  keeps the last valid shell.
- Generated utilities use native CSS scope and cascade layers. Authored
  `app.css` stays unlayered. Scripted views use a document reload for HTML and
  module changes so the browser owns ESM evaluation.
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
- Keep browser tests focused on behavior that crosses the editor, kernel,
  filesystem, and preview documents. Add focused regressions at the package
  that owns each browser failure.
- Keep comments for lifecycle, compatibility, serialization, and failure
  constraints. Remove comments that narrate ordinary code or the change itself.

## Contributor guides

- [Architecture](development_docs/architecture.md)
- [Frontend workspace](development_docs/frontend.md)
- [Releasing](development_docs/releasing.md)
