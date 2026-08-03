# Architecture

Marimo Studio loads inside Marimo through server middleware and a kernel
extension. Marimo remains responsible for the ASGI process, authentication,
notebook execution, session ownership, native routes, and virtual files.

## Boundaries

| Boundary       | Owner                      | Contract                                                         |
| -------------- | -------------------------- | ---------------------------------------------------------------- |
| Command line   | `marimo_studio._cli`       | Inspect notebooks and manage Studio configuration                |
| Workspace      | `marimo_studio._workspace` | Resolve configuration, bindings, views, and authored files       |
| ASGI process   | Marimo                     | Lifecycle, authentication, native APIs, and sessions             |
| Server adapter | `marimo_studio._server`    | Studio pages, custom views, support routes, and HTTP translation |
| Compatibility  | `marimo_studio._compat`    | Translate private Marimo APIs into Studio-owned types            |
| Kernel session | Marimo                     | Reactive execution, caches, controls, and widget models          |
| Browser build  | `apps/browser`             | Compose entrypoints and finalize packaged assets                 |
| View document  | `packages/presentation`    | Render the custom view and mount the Marimo runtime              |
| Studio         | `packages/studio`          | Coordinate panes, source editors, views, and preview             |
| Wire protocol  | `packages/protocol`        | Define Zod schemas for messages and server responses             |
| Marimo adapter | `packages/marimo-frontend` | Contain unstable Marimo frontend imports and build integration   |

Dependencies follow two inward paths:

```text
Python entrypoints -> application services -> _workspace -> records and primitives
                  \-> server composition --> _compat ----/

apps/browser -> presentation -> protocol
             |              \-> marimo-frontend
             \-> studio ------> protocol
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

Run mode serves the default view at `/` and named views at `/<view>/`. Each
browser receives an isolated run session.

Edit mode sends the authenticated root to `/studio/<default-view>/`. The
workspace embeds Marimo's native editor through its `file` selector. A custom
view connects as a kiosk consumer after the editor session exists. Accepted
control writes and anywidget model changes propagate between consumers in that
session.

Studio support routes live under `/_marimo-studio/`. Route construction must
include the parent ASGI mount and Marimo `base_url`. Authentication and native
Marimo routes pass through the middleware.

Notebook query parameters synchronize across the Studio URL, native editor,
and preview. File selection, authentication, transport, and session parameters
remain scoped to the document that owns them.

## Presentation lifecycle

Each custom document keeps one Marimo runtime root mounted for its lifetime.
React portals project cell outputs into `<marimo-cell>` hosts. `mo-value` hosts
read permitted kernel values. HTMX may replace authored shell markup while the
runtime, transport connection, output plugins, and widget models stay mounted.

The server validates bindings against the active Marimo document by semantic
cell identity. Missing cells and values become structured projection
diagnostics while healthy hosts continue rendering. A source refresh commits
HTML, CSS, runtime configuration, and the selected view at one presentation
revision. The browser keeps the last valid shell during transient or invalid
updates.

View source reads and writes use content revisions. Writes use atomic
replacement and reject mutable symlink traversal. External edits refresh clean
editors and produce a conflict beside dirty editors.

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

Keep protocol changes aligned across Python response models, browser schemas,
diagnostic output, support routes, storage keys, and query parameters.

## Runtime checks

Changes to server or session behavior should cover configured and unconfigured
notebooks, edit and run modes, default and named views, authentication, and a
nonempty `base_url`. Exercise cell output, values, controls, anywidgets, HTMX,
virtual files, source refresh, and view switching in a real browser.
