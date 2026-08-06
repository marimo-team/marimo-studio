# Frontend workspace

The pnpm workspace contains the custom view document, the editor workspace,
their shared contracts, the browser build, the documentation site, and live
browser acceptance tests.

## Package responsibilities

| Path                       | Responsibility                                                          |
| -------------------------- | ----------------------------------------------------------------------- |
| `packages/protocol`        | Zod schemas and inferred types for browser and server records           |
| `packages/runtime`         | Runtime registry and document-scoped session interface                  |
| `packages/presentation`    | Custom view document, projections, runtime adapters, and generated CSS  |
| `packages/studio`          | Workspace UI, source editing, view management, and preview coordination |
| `packages/marimo-frontend` | Adapters around Marimo's unstable frontend modules and build setup      |
| `apps/browser`             | Vite entry points, shared chunks, browser assets, and build metadata    |
| `apps/e2e`                 | Playwright fixture and live `marimo edit` acceptance tests              |
| `apps/docs`                | VitePress application and site configuration                            |

`apps/browser` is the composition root. Its runtime entry registers the
Server and WebAssembly presentation runtimes. Its Studio entry injects the
Marimo control and theme frame adapters into the workspace.

Root `vite.config.ts` enforces package imports:

- Protocol imports no Studio package and performs no network, filesystem, DOM,
  or window I/O.
- Runtime imports protocol and performs no Marimo, React, or browser I/O.
- Presentation imports protocol, runtime, and named Marimo frontend adapters.
- Studio imports protocol and stays independent of presentation and Marimo
  frontend code.
- Marimo frontend imports no Studio package.

## Studio feature ownership

Studio follows `app -> features -> shared`.

| Slice                     | Responsibility                                                      |
| ------------------------- | ------------------------------------------------------------------- |
| `app/`                    | Construct services, routes, theme integration, and the React root   |
| `features/navigation/`    | Mode, runtime, view, and workspace controls                         |
| `features/preview/`       | Stable runtime frames, query sync, and native control sync          |
| `features/source-editor/` | Source reads, edits, saves, external updates, and conflicts         |
| `features/views/`         | View creation, selection, removal, and transition coordination      |
| `features/workspace/`     | Pane tree, modes, geometry, resizing, and persisted layout          |
| `shared/`                 | Theme state, external-store binding, errors, icons, and UI controls |

`app/` may compose feature controllers. Feature slices stay independent of
`app/` and communicate through typed controllers. `shared/` imports no app or
feature module. Keep the graph acyclic.

Presentation groups code by document responsibility:

| Slice             | Responsibility                                                     |
| ----------------- | ------------------------------------------------------------------ |
| `document/`       | Authored shell, view navigation, query sync, styles, and refreshes |
| `runtime-config/` | Fetch, validate, stage, and commit runtime configuration           |
| `runtime/`        | Mount runtimes, output plugins, cells, controls, and anywidgets    |
| `cells/`          | Discover and preserve `<marimo-cell>` hosts                        |
| `values/`         | Read values and publish the `mo-value` DOM contract                |
| `view-styles/`    | Generate scoped Wind4 utilities from authored classes              |

## Work on one package

Install the locked workspace once:

```console
make install
```

Run the owning package test while iterating:

```console
pnpm --filter @marimo-studio/protocol test
pnpm --filter @marimo-studio/runtime test
pnpm --filter @marimo-studio/presentation test
pnpm --filter @marimo-studio/studio test
pnpm --filter @marimo-studio/marimo-frontend test
```

Run the browser type and import-boundary checks from the repository root:

```console
pnpm typecheck
pnpm lint
```

Build the document entry points after changing presentation, Studio, runtime,
protocol, or Marimo adapter code:

```console
make build
```

Run the live acceptance suite when a change affects sessions, frames, source
files, projections, native controls, runtime switching, or responsive layout:

```console
make e2e
```

Use `make e2e-ui` to inspect the Playwright flow interactively.

## Marimo frontend adapter

`packages/marimo-frontend` contains every import from Marimo's unstable
frontend surface, Marimo's `@/` alias, and the source preparation required by
Vite.

The preparation command reads the Marimo version resolved by `uv.lock`, checks
out the pinned matching commit under `packages/marimo-frontend/.cache/`,
installs its frontend workspace, and records the source metadata:

```console
pnpm --filter @marimo-studio/marimo-frontend prepare:upstream
```

A Marimo upgrade changes both the Python lockfile and `expectedCommit` in
`packages/marimo-frontend/scripts/source.mjs`. Run adapter tests and rebuild
the browser bundle after updating them.

Set `MARIMO_REPO` to exercise a local checkout whose project version matches
the Python environment:

```console
MARIMO_REPO=/path/to/marimo make build
```

Keep upstream source paths, registry access, Marimo frame behavior, and build
aliases inside this package. Other packages consume named adapters such as the
control endpoint and theme frame.

## Browser build

`make build` prepares Marimo source and builds the entry points from
`apps/browser` into:

```text
packages/marimo-studio/src/marimo_studio/_static/browser/
```

The build emits `runtime.js`, `dev-reload.js`, `studio.js`, their CSS files,
shared chunks, worker assets, and `build-meta.json`. The generated directory
and prepared Marimo checkout stay untracked. Change workspace source, rebuild,
then run `make package` when distribution contents are part of the change.

## Browser acceptance ownership

Package tests protect local contracts. `apps/e2e` protects flows that require a
live Marimo kernel and several documents.

| Acceptance area      | Current contract                                                           |
| -------------------- | -------------------------------------------------------------------------- |
| Runtime lifecycle    | Editor, Server, and WebAssembly frames remain mounted across mode changes  |
| Control sync         | JSON-compatible native controls synchronize between editor and runtimes    |
| Runtime isolation    | Anywidget state remains with the runtime that owns its model               |
| Source authoring     | Studio and external edits update files and the live preview safely         |
| View management      | Creating and removing a view updates source files and the selected preview |
| Projection recovery  | A missing value host recovers after its notebook definition returns        |
| Responsive workspace | The compact layout remains operable without page-level overflow            |

Add a focused regression to the owning package first. Add browser acceptance
when the failure crosses the editor, kernel, filesystem, runtime, or document
boundary.
