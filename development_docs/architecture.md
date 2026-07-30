# Architecture

Marimo owns the application process, notebook sessions, kernels, and native
routes. Marimo Studio registers presentation middleware and a kernel extension
inside that process.

## Boundaries

| Boundary | Owner | Contract |
| --- | --- | --- |
| Command line | `marimo_studio._cli` | Parse arguments, call services, render text or JSON |
| Workspace | `marimo_studio._workspace` | Resolve configuration, views, aliases, checks, and launch plans |
| ASGI process | Marimo | Lifecycle, authentication, native routes, and session manager |
| Presentation | `marimo_studio._server` | View documents, Studio workspace, and support routes |
| Kernel session | Marimo | Reactive graph, execution, caches, controls, and widget models |
| Value bridge | `marimo_studio._compat` | Read permitted selectors through the kernel command queue |
| Browser runtime | Marimo adapter | WebSocket, store, output plugins, and widget models |
| View source | Notebook author | HTML, CSS, static files, cell hosts, and value hosts |

HTMX can add or remove projection hosts. Marimo remains responsible for kernel
creation, execution, invalidation, and caching.

## Activation

The package registers two Marimo entry points:

```toml
[project.entry-points."marimo.server.asgi.middleware"]
marimo-studio = "marimo_studio._entrypoints:server_middleware"

[project.entry-points."marimo.kernel.lifespan"]
marimo-studio = "marimo_studio._entrypoints:kernel_lifespan"
```

The middleware discovers Studio configuration from the active notebook before
handling a presentation route. The kernel extension registers the value reader
for configured notebooks. An unconfigured notebook continues through Marimo's
regular server and kernel paths.

Configuration resolves from notebook PEP 723 metadata or the nearest parent
`pyproject.toml` that names the notebook. Views resolve from
`__marimo__/studio/<notebook-stem>/<view-name>/`.

## Command flow

`marimo_studio._cli.main` registers each command explicitly. Command modules
translate Click values into calls to notebook inspection and workspace
services. Output modules own human text, terminal color, JSON, and diagnostic
events.

The direct launcher passes a `LaunchRequest` to
`marimo_studio._workspace.launch`. The service validates arguments before
creating view files, resolves authentication, and returns a `LaunchPlan`.
Execution opens the Studio URL when requested and starts `marimo edit` in the
notebook environment.

Keep Click imports and terminal presentation inside `_cli`. Workspace services
should accept Python values and raise domain errors that tests can exercise
directly.

## Server and session flow

Run mode serves the configured default view at `/` and named views at
`/<view>/`. Each browser document receives an isolated Marimo run session.

Edit mode keeps the editor at `/`. `/studio/` opens the editor and default view,
while `/studio/<view>/` selects another view. A standalone `/<view>/` document
connects to the editor kernel as a kiosk consumer after the primary editor
session exists.

Studio support routes live under `/_marimo-studio/`. Public and support URLs
include the parent ASGI mount and Marimo `base_url`. Native Marimo routes pass
through the middleware.

## Browser flow

Each custom document contains one hidden `#marimo-runtime-root`. It owns the
Marimo store, WebSocket, output plugins, and widget models for the document
lifetime. React portals render cell outputs into `<marimo-cell>` hosts. Value
requests travel through the active browser consumer and the kernel command
queue.

View switches and HTML refreshes replace `#app-shell` while the runtime root
stays mounted. See [Frontend](frontend.md) for refresh and build contracts.

## Projection lifecycle

Workspace resolution treats document structure and projection identity as
separate contracts. Invalid HTML structure stops the selected document.
Missing cells, stale aliases, and undefined value roots remain attached to the
resolved view as structured diagnostics. Valid bindings continue into the
runtime configuration.

The browser renders each projection diagnostic at its host.
`window.marimoStudio.diagnostics()` combines those records with presentation
refresh failures and browser delivery failures. `check` serializes projection
findings to JSON and JSON Lines with the view, target, template location, and
repair hint. A notebook or template save recomputes the records and clears a
repaired host without replacing the kernel session.

Before publishing new bindings, the server compares the selected view's named
and anonymous cells with the active Marimo document by semantic identity. An
unrelated notebook edit cannot block the view. A document that is still
receiving a required edit returns a transient sync response. The browser keeps
the last healthy configuration, reports a loading state, and retries with
capped backoff.

Every view document and runtime configuration carries a presentation revision.
The browser commits a shell refresh after both responses report the same
revision. The revision includes the selected view and source content. A
concurrent file save produces a transient retry while the last coherent
presentation stays active.

A value projection clears its rendered value when its notebook root
disappears. Cached values remain visible during transient kernel reads. A cell
binding that never reaches the browser store changes from a loading skeleton
to a local runtime diagnostic after the delivery window.

## Compatibility

Private Marimo Python imports stay in `src/marimo_studio/_compat/`. Imports from
`@marimo-team/frontend/unstable_internal` stay in
`frontend/src/marimo-adapter/`.

The package supports Marimo 0.23.14 and newer. CI tests the lower bound and the
version resolved in `uv.lock`. The browser build uses that locked version.

Kernel sessions live in one process. Production deployments use one worker or
route each browser back to the process that owns its session.
