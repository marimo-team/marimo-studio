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
| `src/marimo_studio/_server/` | View documents, Studio, support routes, development events |
| `src/marimo_studio/_compat/` | Private Marimo Python integration |
| `frontend/src/` | Projection hosts, readiness, HTMX, refresh, Studio |
| `frontend/src/marimo-adapter/` | Unstable Marimo frontend integration |
| `docs/` | User workflows and reference |
| `development_docs/` | Architecture, frontend maintenance, releases |

Authored view source lives at
`__marimo__/studio/<notebook-stem>/<view>/` beside its notebook.

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
- `<marimo-cell>` renders through Marimo's output and widget clients.
- `mo-value` reads selectors permitted by the active view through the kernel
  queue.
- Every projection host lives inside the single `#app-shell`.
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
- the `mo-value` parser, view allowlist, kernel RPC, and browser binding
- the Marimo lower bound in `pyproject.toml` and the resolved version in
  `uv.lock` and browser build metadata
- support routes, browser events, storage keys, and query parameters

## Mutation rules

Direct launch and `view add` may update PEP 723 metadata. Preserve every
notebook byte outside that block, unrelated dependencies, tool tables, uv
sources, indexes, encoding cookies, and line endings.

Validate launch options before writing. Use atomic writes and reject mutable
symlink traversal. A repeated setup or binding command should converge without
rewriting unchanged files.

New views start as a blank `#app-shell`. Keep their HTML, CSS, and static files
as authored source.

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
