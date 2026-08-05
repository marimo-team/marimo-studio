# Frontend workspace

The root pnpm workspace contains two browser documents and one build
composition root. Vite Plus provides formatting, linting, type-aware checks,
tests, builds, and task orchestration.

## Packages

| Path                                            | Responsibility                                         |
| ----------------------------------------------- | ------------------------------------------------------ |
| `apps/browser/`                                 | Vite entrypoints, shared chunks, and packaged metadata |
| `packages/runtime/`                             | Runtime adapter and session lifecycle contracts        |
| `packages/presentation/`                        | Custom-view document, projections, and runtime mount   |
| `packages/studio/`                              | Studio composition, feature slices, and shared UI      |
| `packages/protocol/`                            | Browser messages and validated server response records |
| `packages/marimo-frontend/src/upstream/`        | Imports from Marimo's unstable frontend surface        |
| `packages/marimo-frontend/src/control-frame.ts` | Adapt a Marimo frame to native control operations      |
| `packages/marimo-frontend/src/theme-frame.ts`   | Read the resolved theme from the native editor frame   |
| `packages/marimo-frontend/src/vite.ts`          | Marimo aliases and PostCSS                             |
| `packages/marimo-frontend/scripts/`             | Locked Marimo source preparation and build metadata    |
| `apps/docs/`                                    | VitePress application and site configuration           |

`packages/runtime` defines the transport-independent adapter contract.
`packages/presentation` renders the custom view and keeps the shared React
renderer as a private module. `packages/studio` mounts the workspace from the
server's validated bootstrap record. React owns the toolbar, pane tree, source
editors, and stable notebook and preview frames.
`packages/protocol` is the shared wire boundary. Zod 4 schemas validate input
and define the TypeScript types consumed by both documents. The package
contains no fetch, EventSource, DOM, or window access.

Presentation groups code by lifecycle. `document/` owns the authored shell,
`cells/` and `values/` own projection hosts, `runtime-config/` owns the server
contract, and `runtime/` owns the Marimo React mount.

Studio follows `app → features → shared`. `app/` constructs services, routes,
theme resolution, and the root document. Feature slices own their components,
state, browser I/O, and styles. `navigation/` and `workspace/` compose sibling
features through typed controllers. The feature graph stays acyclic. `shared/`
contains theme state, external-store binding, errors, and UI primitives that
several features consume.

Keep upstream module paths, Marimo's `@/` alias, source checkout details, and
build shims inside `packages/marimo-frontend`. Other packages consume its
named adapter exports.

## Workspace policy

`pnpm-workspace.yaml` owns package membership, dependency catalogs, overrides,
and install policy. Add JavaScript dependencies to the package that imports
them and reuse catalog versions for shared dependencies.

Root `vite.config.ts` owns Vite Plus formatting, linting, type-aware checks,
and cross-package import restrictions. Package scripts own package-specific
build, test, source preparation, and documentation commands.

Use the root workspace commands:

```console
pnpm install --frozen-lockfile
pnpm check
pnpm test
pnpm typecheck
pnpm build
```

The equivalent repository gates are available through `make install`,
`make check`, and `make build`.

## Marimo source adapter

`pnpm --filter @marimo-studio/marimo-frontend prepare:upstream` resolves the
Marimo version installed by `uv.lock`. The adapter pins the matching Git commit,
prepares a clean checkout under `packages/marimo-frontend/.cache/`, and records
its version and commit. Repeated checks reuse a clean, fully installed checkout.
A changed commit, tracked source edit, or incomplete install rebuilds the cache.
Update the pinned commit in
`packages/marimo-frontend/scripts/source.mjs` with a Marimo lockfile upgrade.

Set `MARIMO_REPO` to use a local checkout with the same version:

```console
MARIMO_REPO=/path/to/marimo make build
```

Vite Plus checks the adapter against the prepared Marimo frontend source. A
Marimo upgrade should concentrate path and declaration changes in
`packages/marimo-frontend`.

## Generated assets

`pnpm build` prepares Marimo source, builds the entrypoints from
`apps/browser`, and writes one browser bundle to
`packages/marimo-studio/src/marimo_studio/_static/browser/`. A Vite plugin emits
`build-meta.json` with the Marimo and HTMX versions in the same build.

The generated directory and Marimo source cache stay untracked. Change source
under `packages/`, rebuild, and verify package contents with `make package`.

## Browser contracts

The custom view keeps `#marimo-runtime-root` mounted while scriptless HTML
refreshes or a view switch replaces `#app-shell`. Matching cell hosts reconnect
to the current store and preserve output DOM when possible. A document with an
authored script reloads for HTML and module changes so the browser evaluates
the native module graph through its normal lifecycle. Studio installs
`window.htmx` and starts utility-class observation before authored modules can
mutate the shell.

`values/` owns the DOM contract for Python value projections. The active
adapter supplies JSON values, then each matching host receives its own cloned
snapshot. The host updates `marimoValue`, text content, and `data-state` before
dispatching `marimo-value-updated`. Errors clear the snapshot and publish
`marimo-value-error` after diagnostic attributes are ready. Readiness evaluates
in a microtask, which keeps `marimo-studio:idle` as the batch boundary after
per-host events.

Wind4 output is wrapped in native CSS `@scope` and stops at
`[data-marimo-cell-output]`. Studio foundation and utility rules use named
cascade layers. The authored `app.css` remains unlayered and follows standard
cascade precedence. Unsupported `@scope` browsers retain authored CSS and the
notebook runtime and receive a focused style diagnostic.

Studio keeps the notebook iframe, source editors, and prepared runtime preview
frames mounted as stable nodes. Task modes and the custom pane tree change
their rectangles while runtime selection changes which preview frame is
visible. Source editors use content-derived ETags and `If-Match` writes.
Studio follows the native editor's resolved light or dark theme. The browser
app injects that frame adapter, while Studio applies its own theme tokens,
source editor theme, and matching brand mark.

Studio prepares the WebAssembly preview while the Server frame is active. When
it becomes ready, Studio requests the server and preview semantic cell maps at
the same presentation revision. The browser app injects Marimo frame adapters
into Studio, subscribes to control registration, and sends the editor snapshot
to the preview in one kernel request. Later JSON-compatible native control
updates travel in both directions. Read-only value and query RPCs retry
transient worker deadlines. The Marimo compatibility package owns registry
and request-client access. Studio owns translation, lifecycle, retry, and
cancellation.

Tests live with their owner. Protocol tests exercise schemas and concrete
envelopes. Presentation and Studio tests exercise their state and lifecycle
contracts. Exercise changes that cross documents or sessions in a real
browser, including desktop and narrow layouts, failed requests, console
errors, cell output, controls, anywidgets, view switching, source saves, and
external edits.
