# Frontend workspace

The pnpm workspace builds two browser documents: the authored presentation and
the Studio authoring workspace. Work in the package that owns the behavior,
then cross package boundaries through protocol records, the runtime interface,
or an injected feature port.

Read [Browser runtime and
authoring](architecture/browser-runtime-and-authoring.md) for the semantic and
lifecycle map behind these packages.

## Choose the owning package

| Package                    | Owns                                                                            | Typical change                                                                                           |
| -------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `packages/protocol`        | Zod schemas and inferred browser and server records                             | Add a field to runtime configuration or a development event                                              |
| `packages/runtime`         | Runtime registration, mount, update, query, and disposal interface              | Add a runtime lifecycle capability shared by Server and WebAssembly                                      |
| `packages/presentation`    | One authored document, revision transaction, projections, styles, and readiness | Change HTML refresh, a projection host, or browser readiness                                             |
| `packages/studio`          | Notebook, source, preview workspace and feature controllers                     | Change navigation, layout, source editing, view management, or frame coordination                        |
| `packages/marimo-frontend` | Named adapters around Marimo's unstable frontend modules                        | Change native rendering, embedded runtime composition, controls, session bootstrap, or theme integration |
| `apps/browser`             | Final runtime and Studio entry-point composition                                | Register a runtime or inject a frame adapter                                                             |
| `apps/e2e`                 | Live Marimo and Chromium acceptance                                             | Prove behavior across editor, kernel, filesystem, session, worker, and preview                           |
| `apps/docs`                | VitePress delivery                                                              | Change site navigation, theme, metadata, search, or docs build behavior                                  |

## Install and run focused checks

Install the locked workspace:

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
make typecheck
make lint
```

Build browser entry points after changing protocol, runtime, presentation,
Studio, browser composition, or Marimo frontend code:

```console
make build
```

Run live acceptance after changing sessions, frames, source files,
projections, controls, query state, runtime switching, view transitions, or
responsive layout:

```console
make e2e
```

Use `make e2e-ui` to inspect the Playwright flow interactively.

## Preserve package direction

Root `vite.config.ts` enforces these imports:

- Protocol imports no Studio package and performs no network, filesystem,
  document object model, or window I/O.
- Runtime imports protocol and performs no Marimo, React, or browser I/O.
- Presentation imports protocol, runtime, and named Marimo frontend adapters.
- Studio imports protocol and stays independent of presentation and Marimo
  frontend code.
- Marimo frontend imports no Studio package.
- `apps/browser` composes package entry points.

Within `packages/studio`, source follows `app -> features -> shared`.
Feature slices import no app module. Shared primitives import no app or feature
module.

Use `app/` for coordination that crosses features. Keep view inventory in the
views feature, source persistence state in the source-editor feature, runtime
frames in the preview feature, and pane geometry in the workspace feature.

## Change a protocol record

A protocol change is complete when the same semantic field reaches every
owner that reads or writes it.

1. Change the Zod schema and inferred type in `packages/protocol`.
2. Update the Python producer or parser.
3. Update every browser consumer.
4. Add a concrete fixture that represents the supported behavior.
5. Test malformed or stale input when it can affect mutation, navigation,
   session identity, or agent evidence.
6. Run protocol tests, the owning producer and consumer tests, type checks, and
   browser acceptance for a cross-document behavior.

Avoid duplicating validation constants in producers and consumers. Let the
schema own the browser record and let the Python model own its server shape.

## Change the presentation document

Presentation code is grouped by document responsibility:

| Slice             | Owns                                                                                                                         |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `document/`       | Revision transactions, authored shell mutation, navigation, base URL, styles, scripts, query observation, and session replay |
| `projections/`    | Shared host registration, preservation, connection, disposal, and readiness contribution                                     |
| `cells/`          | `<marimo-cell>` host discovery and preservation                                                                              |
| `outputs/`        | `<marimo-output>` host discovery, requests, and preservation                                                                 |
| `values/`         | `mo-value` hosts, browser properties, and events                                                                             |
| `runtime-config/` | Fetch, validate, stage, and commit runtime configuration                                                                     |
| `runtime/`        | Runtime mount, cell portals, output portals, values, controls, and transport                                                 |
| `view-styles/`    | Scoped Wind4 utility generation and foundation styles                                                                        |

`PresentationRevisionController` owns every HTML, CSS, runtime, and view
transition. Add a new transition through that controller so cancellation,
staging, rollback, runtime updates, session replay, and readiness remain one
transaction.

`ProjectionHostRuntime` owns the adapter list for projection hosts. A new host
type joins document preparation, preservation, connection, disposal, change
notification, and readiness through that boundary.

Test a presentation change at three levels when applicable:

1. The local reducer, parser, or adapter contract.
2. The composed document transition or runtime integration.
3. A live Server and WebAssembly path when runtime ownership differs.

## Change the Studio workspace

Studio features expose controller snapshots through React external stores.
Keep mutations in the controller that owns the state:

| Feature       | Controller responsibility                                                                         |
| ------------- | ------------------------------------------------------------------------------------------------- |
| Navigation    | Map user actions to layout, runtime, and view controller calls                                    |
| Workspace     | Pane tree, modes, placement, geometry, resizing, compact state, and per-view storage              |
| Source editor | File buffers, autosave, revisions, external changes, conflicts, and active source tab             |
| Views         | Inventory, selection, creation, removal, and transition cancellation                              |
| Preview       | Stable frames, runtime status, query sync, control sync, observations, and editor session changes |

`WorkspaceEventCoordinator` is the server-event boundary. Add an event there
when the event coordinates several features. Keep feature-local browser events
inside the feature.

Visible changes require browser inspection at desktop and narrow widths. Check
keyboard operation, focus, overflow, pane resizing, hidden frames, runtime
status, source conflicts, and error recovery as the feature requires.

## Change the Marimo frontend facade

`packages/marimo-frontend` contains imports from Marimo's unstable frontend
surface, Marimo's `@/` alias, and the source preparation needed by Vite.
Presentation and Studio import named facade capabilities:

- `embedded-runtime`
- `cell-presentation`
- `projected-output`
- `session-bootstrap`
- `control-endpoint`
- `theme-frame`
- `vite`

Keep upstream atoms, providers, registries, transport managers, source paths,
and frame globals inside the facade. Expose the smallest behavior and lifecycle
that the caller needs. A stateful facade returns a handle or endpoint with an
explicit `dispose` or `close` boundary.

Prepare the exact Marimo frontend source with:

```console
pnpm --filter @marimo-studio/marimo-frontend prepare:upstream
```

The command reads the version resolved by `uv.lock`, checks out the commit from
`_compat/release.json` under `packages/marimo-frontend/.cache/`, installs its
frontend workspace, and records source metadata.

Set `MARIMO_REPO` to use a clean local checkout at the configured release
commit:

```console
MARIMO_REPO=/path/to/marimo make build
```

A Marimo upgrade changes the release manifest, exact Python pins, private
symbol contracts, frontend source preparation, affected facade adapters, and
their tests together. Follow [Marimo integration](architecture/marimo-integration.md)
and [Releasing](releasing.md).

## Inspect the browser build

`make build` emits:

```text
packages/marimo-studio/src/marimo_studio/_static/browser/
```

The output contains `runtime.js`, `dev-reload.js`, `studio.js`, their CSS,
shared chunks, worker assets, and `build-meta.json`. Build metadata records the
Marimo version and release commit.

The generated browser directory and prepared Marimo checkout remain
untracked. Change workspace source, rebuild, then use `make package` when the
distribution contents are part of the contract.

## Add browser acceptance at the product seam

Package tests protect local behavior. Add `apps/e2e` coverage when a failure
requires several owners to reproduce.

| Seam                  | Representative evidence                                                        |
| --------------------- | ------------------------------------------------------------------------------ |
| Document and runtime  | Native output persists across valid HTML refresh and updates after rerun       |
| Runtime frames        | Server and WebAssembly remain mounted across workspace modes                   |
| Resource ownership    | A projected control remains until the final owner disappears                   |
| Runtime isolation     | Anywidget state stays with its owning runtime                                  |
| Source and filesystem | Browser edits, external edits, conflicts, and deletion converge                |
| View transition       | Source saves, successor preparation, route, and preview update in order        |
| Session identity      | Preview reattaches after editor reconnect and run mode replays when configured |
| Agent evidence        | Activation and observation match view, revision, runtime, session, and request |
| Responsive workspace  | Studio and authored content remain operable at narrow width                    |

Start with one focused package regression, then add the live case that proves
the cross-boundary failure mode.
