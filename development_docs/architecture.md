# Architecture

Marimo is the application server. Marimo Studio is opt-in presentation
middleware inside that server.

```text
Marimo ASGI application
  authentication
  native API and WebSocket routes
  notebook session manager
  kernel and reactive graph
  virtual files and notebook assets
  Marimo Studio middleware
    custom view documents
    Studio workspace
    cell and value support routes
    development events
```

## Ownership

| Boundary | Owner | Contract |
| --- | --- | --- |
| Workspace | Notebook author | Notebook, Studio configuration, view folders |
| ASGI process | Marimo | Lifecycle, authentication, native routes, notebook workspace |
| Kernel session | Marimo | Graph, execution, caches, controls, widget models |
| Presentation | Marimo Studio | View documents, Studio, namespaced support routes |
| Browser runtime | Marimo adapter | WebSocket, store, plugins, output portals |
| Cell host | View and HTMX | Projection of one displayed cell |
| Value host | View and kernel RPC | Projection of one permitted selector |

An HTMX request can add or remove projection hosts. Marimo remains responsible
for kernel creation, execution, invalidation, and caching.

## Activation

The distribution registers two entry points:

```toml
[project.entry-points."marimo.server.asgi.middleware"]
marimo-studio = "marimo_studio._entrypoints:server_middleware"

[project.entry-points."marimo.kernel.lifespan"]
marimo-studio = "marimo_studio._entrypoints:kernel_lifespan"
```

Both inspect the active notebook and remain inert when it has no matching
`[tool.marimo-studio]` configuration.

Configuration resolves from notebook PEP 723 metadata or the nearest parent
`pyproject.toml` that names the notebook. Authored views resolve directly from
`__marimo__/studio/<notebook-stem>/<view-name>/`.

## Server flow

The middleware reads the notebook path, mode, base URL, authentication state,
and session manager from Marimo application state.

Run mode presents the configured default view at `/` and named views at
`/<view>/`. Each browser document receives Marimo's regular isolated run
session.

Edit mode keeps the native editor at `/`. `/studio/` opens the default Studio
workspace and `/studio/<view>/` selects a named view. The standalone
`/<view>/` document connects as a kiosk consumer after the editor creates the
primary session, so editor and view share one kernel.

Every Studio URL combines the parent ASGI mount path with Marimo's `base_url`.
Assets, value reads, cell fragments, and development events stay beneath
`/_marimo-studio/`. Other requests pass through to Marimo.

## Browser state

A custom document contains one hidden `#marimo-runtime-root`. It owns the
Marimo store, WebSocket, output plugins, and widget models for the document
lifetime.

React portals render current cell outputs into `<marimo-cell>` hosts. Kernel
value selectors travel through the browser consumer, Marimo session command
queue, and a kernel function registered by the lifespan entry point.

View switching fetches another document and runtime configuration, then swaps
`#app-shell`. The runtime root stays mounted. Matching cell hosts retain their
rendered widget DOM.

HTML refresh follows the same shell transition. A failed replacement leaves
the last valid shell visible. CSS links are staged and committed after they
load.

## Compatibility boundary

Imports from Marimo private Python modules live in
`src/marimo_studio/_compat/`. Imports from
`@marimo-team/frontend/unstable_internal` live in
`frontend/src/marimo-adapter/`.

The package supports Marimo 0.23.14 and newer. `uv.lock` selects the Marimo
source used to build the browser runtime. Compatibility checks exercise the
supported lower bound and the locked development version.

Kernel sessions are process-local. Production deployments use one worker or
sticky routing to the process that owns each session.
