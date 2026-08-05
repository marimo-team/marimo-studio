# Architecture

Marimo Studio loads inside Marimo through server middleware and a kernel
extension. Marimo remains responsible for the ASGI process, authentication,
notebook execution, session ownership, native routes, and virtual files.

## Boundaries

| Boundary       | Owner                      | Contract                                                         |
| -------------- | -------------------------- | ---------------------------------------------------------------- |
| Command line   | `marimo_studio._cli`       | Inspect notebooks, manage views, and export static sites         |
| Workspace      | `marimo_studio._workspace` | Resolve configuration, bindings, views, and authored files       |
| ASGI process   | Marimo                     | Lifecycle, authentication, native APIs, and sessions             |
| Server adapter | `marimo_studio._server`    | Studio pages, custom views, support routes, and HTTP translation |
| Compatibility  | `marimo_studio._compat`    | Translate private Marimo APIs into Studio-owned types            |
| Kernel session | Marimo                     | Reactive execution, caches, controls, and widget models          |
| Browser build  | `apps/browser`             | Compose entrypoints and emit packaged assets                     |
| Runtime model  | `packages/runtime`         | Define presentation adapters and session lifecycle               |
| View document  | `packages/presentation`    | Render the custom view and mount the Marimo runtime              |
| Studio         | `packages/studio`          | Render the workspace and coordinate editors, views, and previews |
| Wire protocol  | `packages/protocol`        | Define Zod schemas for messages and server responses             |
| Marimo adapter | `packages/marimo-frontend` | Contain unstable Marimo frontend imports and build integration   |

Dependencies follow two inward paths:

```text
Python entrypoints -> application services -> _workspace -> records and primitives
                  \-> server composition --> _compat ----/

apps/browser -> presentation -> runtime -> protocol
             |              \-> marimo-frontend
             \-> studio ----------------> protocol
```

Use the `marimo-studio` commands for notebook inspection, aliases, checks, and
view management. Start the runtime through Marimo:

```console
uv run --with marimo-studio marimo edit analysis.py
uv run --with marimo-studio marimo run analysis.py
```

## Activation

The Python distribution registers these entry points:

```toml
[project.entry-points."marimo.server.asgi.middleware"]
marimo-studio = "marimo_studio._entrypoints:server_middleware"

[project.entry-points."marimo.kernel.lifespan"]
marimo-studio = "marimo_studio._entrypoints:kernel_lifespan"
```

The middleware discovers configuration from notebook PEP 723 metadata or the
nearest matching `pyproject.toml`. Configured views resolve from
`__marimo__/studio/<notebook-stem>/<view>/`. Requests for unconfigured
notebooks continue through Marimo.

The kernel extension registers value reads for configured notebooks. Values
travel through Marimo's kernel queue and remain scoped to selectors permitted
by the active view.

## Routes and sessions

Run mode serves the default view at `/` and named views at `/<view>/`. A named
view is also the base for its relative files, so `app.js` in the view directory
is available at `/<view>/app.js`. Each browser receives an isolated run
session.

Edit mode sends the authenticated root to `/studio/<default-view>/`. The
server emits the document envelope and a validated JSON bootstrap record.
`packages/studio` mounts one React root, then keeps the native editor and each
prepared preview in stable frames as the visible layout changes. A custom view
connects as a kiosk consumer after the editor session exists. Accepted control
writes and anywidget model changes propagate between consumers in that session.

A WebAssembly preview owns a separate Pyodide kernel. Studio synchronizes
JSON-compatible native `mo.ui` values through two control endpoints. Runtime
cell IDs are translated through semantic cell references before the value is
applied to the other registry. Each kernel remains responsible for its own
reactive execution. Anywidget comm models remain scoped to the runtime that
created them.

Studio support routes live under `/_marimo-studio/`. Route construction must
include the parent ASGI mount and Marimo `base_url`. Authentication and native
Marimo routes pass through the middleware.

Notebook query parameters synchronize across the Studio URL, native editor,
and preview. WebAssembly applies editor changes through its runtime function
registry. Preview changes enter the editor kernel through Marimo's command
queue. File selection, authentication, runtime selection, transport, and
session parameters remain scoped to the document that owns them.

## Presentation lifecycle

Each custom document selects a `PresentationRuntime` from the browser registry.
The Python `RuntimeProvider` with the same ID projects adapter-specific data,
cell bindings, and value bindings. The protocol treats adapter data as opaque.
The adapter validates that record before mounting.

The server adapter connects to Marimo's session and reads values through the
kernel route. The WebAssembly adapter runs a derived notebook in Marimo's
Pyodide worker and reads values through its function registry. Both use the
same renderer for output plugins, controls, cell portals, and anywidgets.

Runtime providers may include a semantic cell map in their projection. Studio
uses that map to bridge native controls between the editor and the selected
preview runtime. Private UI registry access stays in
`packages/marimo-frontend`. `packages/studio` depends on a small injected
control endpoint and has no Marimo frontend import.

React portals project cell outputs into `<marimo-cell>` hosts. `mo-value` hosts
read permitted values through the active adapter. Each value host exposes an
isolated JSON snapshot through `marimoValue` and native DOM events. HTMX may
replace authored shell markup while that adapter and its widget models stay
mounted. Studio keeps prepared runtime documents in separate frames and
updates each document in place when the view changes. An adapter instance
change reloads its owning preview document.

The styling runtime scans classes outside Marimo-owned output boundaries and
generates Wind4 CSS inside a native `@scope`. Named cascade layers keep Studio
foundation and utility rules below unlayered `app.css`. The browser evaluates
authored module scripts as ordinary ESM. A scripted document reloads after an
HTML or module change so imports and initialization follow a page lifecycle.
The view base keeps authored relative URLs native. View-relative Studio,
virtual-file, notebook-public, and public-service-worker paths route back to
their owning server handlers before authored asset lookup.

The server validates bindings against the active Marimo document by semantic
cell identity. Missing cells and values become structured projection
diagnostics while healthy hosts continue rendering. A source refresh commits
HTML, document-scoped assets, runtime configuration, and the selected view at
one presentation revision. CSS reloads independently. The browser keeps the
last valid shell during transient or invalid updates.

View source reads and writes use content revisions. Writes use atomic
replacement and reject mutable symlink traversal. External edits refresh clean
editors and produce a conflict beside dirty editors.

## Static export

`marimo_studio.export` turns one resolved view into an HTTP-hosted directory.
It snapshots the authored document and notebook source, validates projections,
derives the same browser notebook used by the WebAssembly preview, and writes
an immutable runtime configuration. The output contains the custom document,
selected view files, built-in cell fragments, notebook `public/` files, and the
packaged Studio browser build.

The exported document uses relative URLs so the directory can live beneath a
static host's base path. Pyodide owns notebook execution. The presentation
package still owns output plugins, controls, portals, value reads, and
anywidget models. Export therefore adds a packaging boundary around the
existing WebAssembly runtime.

Output is staged beside the destination and moved into place after every file
has been written. Replacing an existing bundle requires `--force`. Projection
failures leave the destination unchanged. A destination manifest rejects
reserved paths, duplicate files, and file-directory collisions before copying.

Private Marimo access stays in `_compat/static_export.py` and the existing
browser notebook adapter. These public Marimo APIs would narrow that boundary:

- A WASM preparation API that returns canonical notebook source, resolved
  configuration, `public/` files, local wheel artifacts, and optional executed
  snapshots and cache artifacts. Studio could then share Marimo's PEP 723,
  local module, warm-cache, and wheel policy as one operation.
- A stable browser embedding entry point for the Pyodide bridge, output
  plugins, UI elements, and anywidget models. Studio currently contains this
  dependency in `packages/marimo-frontend`.
- A runtime asset manifest and copy API independent of Marimo's native notebook
  document. Custom presentation exporters could consume the same versioned
  worker and chunk graph through a supported contract.
- A public path-scoped configuration resolver for export clients. Studio could
  read the effective user and project settings through a typed API.

## Python dependency direction

`_workspace` owns project rules and imports no Marimo adapter. Operations that
need notebook data depend on the `NotebookInspector` or `RuntimeProber` port.
Top-level application services compose those operations with `_compat`
adapters. `environment.py` likewise composes uv process orchestration with
Marimo's notebook sandbox flags.

Click imports stay in `_cli`. Starlette request and response translation stays
in `_server`. The CLI resolves workspace targets and calls application
services with Python values and Studio-owned records. Server composition may
call `_compat` where a request depends on the active Marimo session.

Private Marimo imports stay in `_compat`. Adapters translate Marimo requests,
sessions, kernel messages, and graph state into records from
`marimo_studio.types`.

Add a runtime at the composition boundary. Register its Python provider with
`PresentationMiddleware`, register its browser definition in `apps/browser`,
and use the same runtime ID on both sides. Runtime code stays in its adapter.
The shared renderer and wire protocol remain transport-independent.

Keep protocol changes aligned across Python response models, browser schemas,
diagnostic output, support routes, storage keys, and query parameters.

## Runtime checks

Changes to server or session behavior should cover configured and unconfigured
notebooks, edit and run modes, default and named views, authentication, and a
nonempty `base_url`. Exercise cell output, values, controls, anywidgets, HTMX,
virtual files, source refresh, and view switching in a real browser.
