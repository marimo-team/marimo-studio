# AGENTS.md

Keep Marimo as the runtime server. Marimo Studio adds custom view documents,
projection routes, and an editor workspace while Marimo owns notebook
execution, sessions, authentication, and native APIs.

## Commands

| Task | Command |
| --- | --- |
| Install | `make install` |
| Format | `make format` |
| Lint | `make lint` |
| Type-check | `make typecheck` |
| Test | `make test` |
| Local gate | `make check` |
| Build browser assets | `make build` |
| Build docs | `make docs-build` |
| Serve docs | `make docs-serve` |
| Build distributions | `make package` |

Run focused checks while working and `make check` before handoff. Run
`make build` and browser acceptance when a change crosses the Python and
TypeScript boundary.

## Ownership

| Path | Responsibility |
| --- | --- |
| `src/marimo_studio/_cli/` | Command registration, Click adapters, diagnostics, terminal output |
| `src/marimo_studio/_workspace/` | Configuration, views, bindings, checks, targets, launch services |
| `src/marimo_studio/_server/middleware.py` | Request dispatch into page and support adapters |
| `src/marimo_studio/_server/` | View documents, support routes, development events, HTTP translation |
| `src/marimo_studio/_compat/server/` | Marimo server state, sessions, replay, programmatic mounts |
| `src/marimo_studio/_compat/kernel_values/` | Marimo kernel registration and value RPC |
| `frontend/src/runtime-config/` | Runtime contract, store, and HTTP client |
| `frontend/src/studio/` | Studio state, remote clients, DOM views, and controllers |
| `frontend/src/marimo-adapter/` | Marimo store, output, widget, and editor adapters |
| `docs/` | User workflows and reference |
| `development_docs/` | Architecture, frontend maintenance, releases |

Authored view source lives at
`__marimo__/studio/<notebook-stem>/<view>/` beside its notebook.

## Dependency rule

- Click imports stay in `_cli`. Command handlers pass Python values to
  workspace services.
- Starlette request and response translation stays in `_server` or the
  programmatic ASGI adapter.
- Imports beginning with `marimo._` stay in `_compat`.
- Middleware, browser entrypoints, and top-level controllers compose concrete
  services. Parsing, filesystem mutation, transport, state transitions, and
  DOM rendering stay in their owning modules.
- Frontend remote clients perform HTTP. State modules remain independent of
  the DOM. Controllers connect remotes, state, and DOM views.

## Invariants

- Notebook authors keep ordinary Marimo cells.
- One notebook can expose several views from one shared binding registry.
- Edit mode keeps the native editor at `/` and opens workspaces beneath
  `/studio/`.
- Edit-mode `/<view>/` documents attach to the editor kernel as kiosk
  consumers.
- Run-mode browser documents receive isolated Marimo sessions.
- View switching preserves the preview runtime, WebSocket, kernel, and widget
  models.
- Pane layout changes preserve the notebook iframe, source editors, preview
  iframe, and their browser state.
- Source saves use content revisions and atomic replacement. External edits
  refresh clean editors and surface a conflict beside dirty editors.
- `<marimo-cell>` renders through Marimo's output and widget clients.
- `mo-value` reads selectors permitted by the active view through the kernel
  queue.
- Every projection host lives inside the single `#app-shell`.
- Missing cells and value roots keep the healthy shell active and publish
  structured projection diagnostics.
- Runtime configuration validates the selected view against the active Marimo
  document by semantic cell identity.
- A shell and its runtime configuration commit from the same content-derived
  presentation revision.
- Template refresh keeps the last valid shell when the replacement fails.
- Support URLs honor both the parent ASGI mount and Marimo `base_url`.
- Studio owns `/studio/`, `/{view}/`, and `/_marimo-studio/`. Native Marimo
  routes pass through unchanged.

## Compatibility

Imports beginning with `marimo._` stay in `src/marimo_studio/_compat/`.
Imports from `@marimo-team/frontend/unstable_internal` stay in
`frontend/src/marimo-adapter/`.

Keep these contracts aligned:

- `NotebookPresentation.runtime_config` and
  `frontend/src/runtime-config.ts`
- workspace projection diagnostics, CLI check output, browser host state, and
  Studio preview status
- presentation revisions in injected mount data, document responses, runtime
  configuration, and the browser refresh transaction
- the `mo-value` parser, view allowlist, kernel RPC, and browser binding
- the Marimo lower bound in `pyproject.toml` and the resolved version in
  `uv.lock` and browser build metadata
- support routes, browser events, storage keys, and query parameters

## Mutation rules

Direct launch, `view add`, and Studio view management may update PEP 723
metadata. Preserve every notebook byte outside that block, unrelated
dependencies, tool tables, uv sources, indexes, encoding cookies, and line
endings.

Validate launch options before writing. Use atomic writes and reject mutable
symlink traversal. A repeated setup or binding command should converge without
rewriting unchanged files.

New views project each notebook cell in source order through a small HTML and
CSS starter. Keep their HTML, CSS, and static files as authored source.

## Tests

Protect public commands, ASGI responses, protocol data, browser state, and
package contents. Prefer the nearest consumer boundary over private helper
details.

Runtime changes cover:

1. Configured and unconfigured notebooks.
2. Run and edit modes.
3. Default and named views.
4. A nonempty Marimo base URL.
5. Native Marimo authentication.
6. Isolated run sessions and a shared edit preview session.
7. Cell output, values, controls, anywidgets, HTMX, and virtual files.
8. View switching, shell refresh, failure recovery, and loading space.

Use a real browser for visible behavior. Check desktop and mobile layouts,
console errors, failed requests, and session identity. Close the browser
session after verification.

Generated runtime assets remain untracked. Rebuild them from `frontend/` and
verify package inclusion through `make package`.
