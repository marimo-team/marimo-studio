# Frontend workspace

The pnpm workspace builds the presentation document and the Studio authoring
workspace. Work in the package that owns the behavior, then cross boundaries
through protocol records, the runtime SPI, or an injected feature port.

Read [Browser runtime and
authoring](architecture/browser-runtime-and-authoring.md) for the lifecycle map
and [Symbolic projections](architecture/symbolic-projections.md) for projection
site and instance semantics.
Use the [canonical ownership map](architecture.md#ownership) for Python and
cross-package responsibility.

## Choose the owning package

| Package                    | Owns                                                                                    | Typical change                                                                        |
| -------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `packages/protocol`        | Zod schemas and inferred browser and server records                                     | Add a project document, artifact, symbol, site, instance, or event field              |
| `packages/runtime`         | Runtime registration, mount, update, query, control, and disposal SPI                   | Add a lifecycle capability shared by Server and WebAssembly                           |
| `packages/presentation`    | Artifact document, revision transaction, projections, styles, navigation, and readiness | Change document publication or projection-host behavior                               |
| `packages/studio`          | Notebook, Source, Preview, views, and workspace controllers                             | Change tabs, source editing, view switching, layout, or frame coordination            |
| `packages/marimo-frontend` | Named adapters around unstable Marimo frontend modules                                  | Change native rendering, embedded runtime, controls, sessions, or theme integration   |
| `apps/browser`             | Final runtime and workspace composition                                                 | Register a runtime or inject a browser adapter                                        |
| `apps/e2e`                 | Live Marimo and Chromium acceptance                                                     | Prove behavior across provider build, filesystem, editor, kernel, worker, and preview |
| `apps/docs`                | VitePress delivery                                                                      | Change site navigation, theme, metadata, search, or docs build behavior               |

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

Run browser type and import-boundary checks from the repository root:

```console
make typecheck
make lint
```

Build browser entry points after changing protocol, runtime, presentation,
Studio, browser composition, or Marimo frontend code:

```console
make build
```

Run live acceptance after changing artifacts, sessions, frames, source files,
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
views feature, source persistence in source-editor, runtime frames in preview,
and pane geometry in workspace.

## Change a protocol record

A protocol change is complete when the same semantic field reaches each
producer and consumer.

1. Change the Zod schema and inferred type in `packages/protocol`.
2. Update the Python producer or parser.
3. Update each browser consumer.
4. Add a concrete valid fixture.
5. Add malformed and stale cases when the record can affect mutation,
   navigation, runtime identity, resource ownership, or agent evidence.
6. Run protocol, producer, consumer, type, and browser checks.

Authoring uses these protocol areas:

| Record area           | Contents                                                                          |
| --------------------- | --------------------------------------------------------------------------------- |
| View project          | View, provider, documents, diagnostics, artifact state                            |
| Source document       | Relative path, language, access, label, and content revision                      |
| Projection targets    | Target names, ready producers, dependency closures, and ambiguity                 |
| Mount declarations    | Mount ID, source location, kind, and allowed targets                              |
| Mounted results       | Instance ID, target, phase, runtime cell, and error                               |
| Runtime configuration | Presentation, runtime, projection targets, mounts, and cell bindings              |
| Development events    | Project, build, presentation, views, ready, activate, observe, and session events |
| Browser observations  | Revision-bound readiness, diagnostics, and mounted-result facts                   |

Avoid duplicating validation constants across producers and consumers. Let the
Python model own server policy and the Zod schema own browser parsing.

## Change the presentation document

Presentation code is grouped by responsibility:

| Slice             | Owns                                                                                                     |
| ----------------- | -------------------------------------------------------------------------------------------------------- |
| `document/`       | Revision transactions, artifact base, navigation, styles, scripts, query observation, and session replay |
| `projections/`    | Site registration, instance identity, preservation, connection, disposal, and readiness                  |
| `cells/`          | `<marimo-cell>` host behavior and cell ownership                                                         |
| `outputs/`        | `<marimo-output>` requests, rendering, preservation, and output ownership                                |
| `values/`         | `mo-value` hosts, browser properties, events, and shared reads                                           |
| `runtime-config/` | Fetch, validate, stage, and commit runtime configuration                                                 |
| `runtime/`        | Runtime mount, portals, values, controls, query, and transport                                           |
| `view-styles/`    | Scoped utility generation and foundation styles                                                          |

`PresentationRevisionController` owns every artifact document and runtime
transition. Add a transition through that controller so cancellation, staging,
rollback, session replay, document base, and readiness remain one transaction.

`ProjectionHostRuntime` owns the adapter list for projection hosts. A new host
type joins site registration, instance lifecycle, document preparation,
preservation, connection, disposal, change notification, and readiness through
that boundary.

Test a presentation change at three levels when applicable:

1. Local reducer, parser, or adapter contract.
2. Composed document transition or runtime integration.
3. Live Server and WebAssembly behavior.

## Change Source

The Source feature renders the provider's `SourceDocumentSpec` catalog. It
contains one editor and one horizontally scrollable tab strip.

| Module             | Responsibility                                                                     |
| ------------------ | ---------------------------------------------------------------------------------- |
| `controller.ts`    | Project catalog, per-view session, active path, buffers, transitions, and disposal |
| `sync.ts`          | One document revision, autosave, external reconciliation, and conflict lifecycle   |
| `remote.ts`        | Project, source read, and conditional source write HTTP calls                      |
| `tabs.ts`          | Keyboard selection model                                                           |
| `SourcePane.tsx`   | Tabs, status, conflict controls, and editor projection                             |
| `SourceEditor.tsx` | CodeMirror, language extensions, read-only state, focus, and save shortcut         |

Provider order is the tab order. The controller retains dirty documents if a
new inspection drops their path, which keeps unsaved work recoverable.

The shipped editor loads syntax modes for HTML, CSS, JavaScript, JSX,
TypeScript, and TSX. JSON, Markdown, Svelte, text, TOML, XML, and external
language IDs use the plain-text mode.

When adding a language:

1. Keep the provider language ID stable.
2. Load the matching CodeMirror extension on demand.
3. Preserve the plain-text fallback.
4. Test editable and read-only files.
5. Inspect the tab and editor at desktop and narrow widths.

## Change view switching

The view feature keeps authoring safety on the commit path and hydrates the
incoming Source session after selection:

1. Flush current editable buffers.
2. Synchronize an authored query when the navigation supplies one.
3. Switch prepared preview controllers to the verified publication.
4. Commit the view, route, query, hash, and layout.
5. Inspect the target project and load its active Source document.
6. Refresh the preview when validation publishes another presentation revision.

`ViewTransition` uses a generation to ignore stale asynchronous results. Keep
the current-session flush ahead of preview commit. Target inspection belongs to
the selected Source session, where a failure becomes a view-scoped diagnostic.

## Change build and workspace events

`WorkspaceEventCoordinator` is the server event boundary. Route each event to
the feature that owns it:

- `project` changes to Source as revision-aware file changes
- `build` changes to Source for project and build-state reconciliation
- `presentation` changes to Source and Preview
- `views` changes to the view inventory
- The initial ready baseline to inventory, Source, and Preview
- Activation and observation requests to the agent coordination path
- Editor session events to Preview

Events carry generation and revision identity where ordering affects behavior.
Controllers discard stale events after a view or runtime switch.

## Change the Studio workspace

Studio controllers expose snapshots through React external stores:

| Feature       | Controller responsibility                                                                  |
| ------------- | ------------------------------------------------------------------------------------------ |
| Navigation    | Map user actions to layout, runtime, view, and Source calls                                |
| Workspace     | Pane tree, modes, placement, geometry, resizing, compact state, and per-view storage       |
| Source editor | Project documents, buffers, autosave, revisions, conflicts, and active tab                 |
| Views         | Inventory, selection, creation, removal, and transition cancellation                       |
| Preview       | Stable frames, runtime status, queries, controls, observations, and editor session changes |

Visible changes require browser inspection at desktop and narrow widths. Check
keyboard operation, focus, overflow, pane resizing, hidden frames, runtime
status, source conflicts, and recovery.

## Change the Marimo frontend facade

`packages/marimo-frontend` contains imports from Marimo's unstable frontend
surface, the upstream `@/` alias, and Vite source preparation. Presentation
imports named facade capabilities:

- `embedded-runtime`
- `cell-presentation`
- `projected-output`
- `session-bootstrap`
- `control-endpoint`
- `theme-frame`
- `vite`

Keep upstream atoms, providers, registries, transport managers, source paths,
and frame globals inside the facade. Expose the smallest behavior and lifecycle
the caller needs. A stateful facade returns a handle with an explicit `dispose`
or `close` boundary.

Prepare the exact Marimo frontend source with:

```console
pnpm --filter @marimo-studio/marimo-frontend prepare:upstream
```

Set `MARIMO_REPO` to use a clean local checkout at the configured release
commit:

```console
MARIMO_REPO=/path/to/marimo make build
```

## Inspect the browser build

`make build` emits:

```text
packages/marimo-studio/src/marimo_studio/_static/browser/
```

The output contains `runtime.js`, `dev-reload.js`, `studio.js`, their CSS,
shared chunks, worker assets, and `build-meta.json`. Build metadata records the
Marimo version and release commit.

Studio targets evergreen browsers with WOFF2 font support. The build keeps one
WOFF2 source for each KaTeX font face.

The generated browser directory and prepared Marimo checkout remain
untracked. Change workspace source, rebuild, then use `make package` when
distribution contents are part of the contract.

`make package` enforces 400 browser files, 24 MiB of browser assets, 600 KiB of
direct runtime and Studio assets, and 120 KiB for their combined gzip payload.
These bounds keep accidental editor, language, diagram, SQL, plotting, AI, and
worker imports visible at the release boundary.

The current facade still prepares an upstream frontend snapshot. New runtime
capabilities should narrow that snapshot through an upstream embedded-renderer
entry point. Expanding the private plugin graph requires a measured budget
change and browser evidence for the capability that needs it.

## Add browser acceptance at the product seam

Package tests protect local behavior. Add `apps/e2e` coverage when a failure
requires several owners to reproduce.

| Seam                  | Representative evidence                                                                  |
| --------------------- | ---------------------------------------------------------------------------------------- |
| Artifact and document | A new build publishes one coherent document and asset tree                               |
| Failed build          | Source reports the diagnostic while the last artifact stays mounted                      |
| Dynamic source        | Mixed-language tabs, read-only locks, conflicts, and new files converge                  |
| Dynamic projections   | React `map` and Svelte `each` instances resolve and release targets                      |
| Runtime frames        | Server and WebAssembly remain mounted across workspace modes                             |
| Resource ownership    | A projected control or output survives until its final owner leaves                      |
| Runtime isolation     | Anywidget state stays with its owning runtime                                            |
| View transition       | Source flush, route and preview commit, then target Source hydration                     |
| Session identity      | Preview reattaches after editor reconnect                                                |
| Agent evidence        | Activation and observation match view, artifact, revision, runtime, session, and request |
| Responsive workspace  | Source tabs and authored content remain operable at narrow width                         |

Start with one focused package regression, then add the live case that proves
the cross-boundary failure mode.
