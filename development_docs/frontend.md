# Frontend workspace

The root pnpm workspace contains two browser documents and one build
composition root. Vite Plus provides formatting, linting, type-aware checks,
tests, builds, and task orchestration.

## Packages

| Path                                            | Responsibility                                          |
| ----------------------------------------------- | ------------------------------------------------------- |
| `apps/browser/`                                 | Vite entrypoints, shared chunks, and asset finalization |
| `packages/runtime/`                             | Runtime adapter and session lifecycle contracts         |
| `packages/presentation/`                        | Custom-view document, projections, and runtime mount    |
| `packages/studio/`                              | Workspace layout, editors, remotes, and controllers     |
| `packages/protocol/`                            | Browser messages and validated server response records  |
| `packages/marimo-frontend/src/upstream/`        | Imports from Marimo's unstable frontend surface         |
| `packages/marimo-frontend/src/control-frame.ts` | Adapt a Marimo frame to native control operations       |
| `packages/marimo-frontend/src/vite.ts`          | Marimo aliases and PostCSS                              |
| `packages/marimo-frontend/scripts/`             | Locked Marimo source preparation and build metadata     |
| `apps/docs/`                                    | VitePress application and site configuration            |

`packages/runtime` defines the transport-independent adapter contract.
`packages/presentation` renders the custom view and keeps the shared React
renderer as a private module. `packages/studio` renders the workspace document.
`packages/protocol` is the shared wire boundary. Zod 4 schemas validate input
and define the TypeScript types consumed by both documents. The package
contains no fetch, EventSource, DOM, or window access.

Presentation groups code by lifecycle. `document/` owns the authored shell,
`cells/` and `values/` own projection hosts, `runtime-config/` owns the server
contract, and `runtime/` owns the Marimo React mount. Studio groups code into
`layout/`, `preview/`, `source/`, and `views/`.

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
`packages/marimo-studio/src/marimo_studio/_static/browser/`. The
finalizer copies authored Studio styles and writes `build-meta.json` with the
Marimo and HTMX versions.

The generated directory and Marimo source cache stay untracked. Change source
under `packages/`, rebuild, and verify package contents with `make package`.

## Browser contracts

The custom view keeps `#marimo-runtime-root` mounted while HTML refreshes or a
view switch replaces `#app-shell`. Matching cell hosts reconnect to the current
store and preserve output DOM when possible.

Studio keeps the notebook iframe, source editors, and preview iframe mounted as
stable nodes. Task modes and the custom pane tree change their rectangles
without moving the nodes between parents. Source editors use content-derived
ETags and `If-Match` writes.

When a WebAssembly preview becomes ready, Studio requests the server and
preview semantic cell maps at the same presentation revision. The browser app
injects Marimo frame adapters into Studio, subscribes to control registration,
and sends the editor snapshot to the preview in one kernel request. Later
JSON-compatible native control updates travel in both directions. The Marimo
compatibility package owns registry and request-client access. Studio owns
translation, lifecycle, retry, and cancellation.

Tests live with their owner. Protocol tests exercise schemas and concrete
envelopes. Presentation and Studio tests exercise their state and lifecycle
contracts. Exercise changes that cross documents or sessions in a real
browser, including desktop and narrow layouts, failed requests, console
errors, cell output, controls, anywidgets, view switching, source saves, and
external edits.
