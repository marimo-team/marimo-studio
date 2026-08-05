---
title: How it works
description: How Marimo Studio adds custom views to Marimo's server, kernel sessions, and browser runtime.
---

# How it works

Run a configured notebook through `marimo edit` or `marimo run`. Marimo starts
the Python process and owns notebook execution. Studio joins that process as a
presentation layer, so the same server can provide the native notebook,
Studio workspace, and custom views.

<ol class="studio-runtime-flow" aria-label="From notebook request to reactive view">
  <li>
    <strong>Marimo starts</strong>
    <span>Marimo loads the notebook, opens its ASGI server, and creates browser-specific kernel sessions.</span>
  </li>
  <li>
    <strong>Studio routes</strong>
    <span>Middleware recognizes configured view URLs and delegates native Marimo traffic unchanged.</span>
  </li>
  <li>
    <strong>The view starts</strong>
    <span>A presentation adapter connects to the Python kernel or starts the notebook in a Pyodide worker.</span>
  </li>
  <li>
    <strong>Marimo reacts</strong>
    <span>Controls update Python state, dependent cells rerun, and native outputs render inside the custom page.</span>
  </li>
</ol>

## ASGI and middleware

[ASGI](https://asgi.readthedocs.io/en/latest/specs/main.html) is the standard
interface between an asynchronous Python server and an application. The
server calls an application with three values:

```python
await app(scope, receive, send)
```

- `scope` describes the connection, including its HTTP path and method or its
  WebSocket type.
- `receive` delivers request events to the application.
- `send` returns response events to the server.

An ASGI middleware has the same callable shape and wraps another ASGI
application. For each connection, it can answer directly or call the wrapped
application. Several middleware layers can therefore compose around one
server application. [Starlette's middleware guide](https://starlette.dev/middleware/)
shows this pure ASGI pattern and its request-routing variants.

Studio registers `PresentationMiddleware` with Marimo through the
`marimo.server.asgi.middleware` Python entry-point group. The middleware reads
the current notebook and server mode from Marimo, then makes one routing
decision:

<div class="studio-request-branch" aria-label="Studio middleware routing decision">
  <section>
    <strong>Studio owns the route</strong>
    <span>Return the editor workspace, a custom view document, or a namespaced support response.</span>
  </section>
  <section>
    <strong>Marimo owns the route</strong>
    <span>Call the wrapped Marimo application with the original scope, receive function, and send function.</span>
  </section>
</div>

The middleware handles HTTP requests for configured notebooks. WebSockets,
authentication, notebook APIs, virtual files, and unrelated paths continue
through Marimo. An unconfigured notebook receives the native Marimo
experience.

## What each side owns

| Owner                | Responsibility                                                                                                      |
| -------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Marimo               | Reactive execution, controls, output plugins, widget models, native APIs, and virtual files                         |
| Studio server        | View discovery, custom documents, the Studio workspace, projection diagnostics, source editing, and support routes  |
| Presentation adapter | Start one Marimo runtime and provide cell output and permitted value reads                                          |
| Studio browser       | Authored page shells, preview frames, view navigation, source refresh, cross-runtime control sync, and output hosts |

For the server runtime, Studio also registers a `marimo.kernel.lifespan` entry
point. It adds a reader for the `mo-value` selectors permitted by the active
view. Reads travel through Marimo's kernel command queue and run against that
browser's Python session.

## Presentation runtimes

Every custom document mounts one `PresentationRuntime`. Each adapter receives
the same validated presentation configuration and returns a session with a
small lifecycle contract: update the current view, request a document reload
when its execution instance changes, and dispose its resources.

**Server** configures Marimo's network request client and joins a Marimo kernel
session. It reads values through Studio's authenticated support route. In edit
mode, the preview joins the editor session as a kiosk consumer, so controls and
anywidget models synchronize between both documents.

**WebAssembly** inserts Marimo's browser-runtime marker, loads the notebook
into a Pyodide worker, and uses Marimo's in-browser request client. Studio
derives the browser source in memory, adds a hidden value reader, and leaves
the notebook file unchanged. Value hosts call that reader through Marimo's
function registry. In the Studio workspace, native control values synchronize
with the editor while each kernel executes its own reactive updates.

Both adapters feed the same renderer. Each preview document owns one adapter,
its cell portals, value hosts, output plugins, UI registry, and anywidget
views. Studio starts the WebAssembly document in the background while the
Server document is active. Selecting a runtime reveals its existing frame. A
future adapter implements the Python `RuntimeProvider` for configuration and
the browser `PresentationRuntime` for execution. The adapter ID joins both
halves while its validated `data` record remains adapter-specific.

## From a cell to the page

A view starts as an ordinary HTML document with an `#app-shell`. Before
returning it, Studio injects runtime assets, connection metadata, and one
hidden `#marimo-runtime-root` near the end of the document.

The runtime root mounts Marimo's frontend store and providers once.
`<marimo-cell name="revenue_chart">` resolves the configured alias to a live
Marimo cell, then a React portal renders that cell's native output into the
element. Tables, controls, downloads, and anywidgets keep their Marimo
behavior through the same output plugins and widget clients used by the
notebook.

`mo-value="report.updated_at"` follows a smaller path. The active adapter reads
an allowed selector from its Python namespace and returns a JSON-compatible
value for the host element. Both adapters use Marimo's globals lock.

CSS edits reload the page stylesheet. HTML edits refresh the authored shell
around the runtime root. A view with native script tags uses a document reload
for HTML and module changes, which gives ESM imports the browser's regular page
lifecycle. Scriptless shell swaps keep the runtime and widget models mounted.
Studio keeps one persistent preview frame per prepared runtime because
Marimo's transport and Pyodide bridge are document-scoped. Runtime selection
changes frame visibility while the notebook editor and source editors remain
mounted.

## Native controls across runtimes

Marimo identifies a UI element as a cell ID followed by its ordinal within the
cell. Those raw cell IDs can differ between the live editor and the derived
WebAssembly notebook. Studio therefore publishes an optional control map for
each runtime:

```text
semantic cell reference -> runtime cell ID -> UI element ordinal
```

After the background WebAssembly preview reports that its runtime is ready,
Studio reads the editor's current UI values and translates them into the
preview's IDs. It then forwards JSON-compatible native control updates in both
directions. Each target runtime receives the value through Marimo's UI
registry and sends it to its own kernel, which reruns the affected graph.

The bridge covers native `mo.ui` values such as sliders, dropdowns, switches,
text fields, and compatible selections. Values that are not JSON-compatible
stay in their originating runtime. Anywidget comm models also stay in their
originating runtime because their model IDs and custom messages have no stable
cross-kernel identity.

Control identity uses the element ordinal within its cell. A notebook must
construct the same native controls in the same order in both runtimes. A cell
that branches on its Python environment can produce a different control at the
same ordinal, so Studio leaves that layout outside the cross-runtime contract.

Anywidgets remain native Marimo outputs in both runtimes. The Server preview
uses the editor's Python models through the shared kernel session. Each
document keeps its own frontend view registry. Trait updates and
kernel-originated custom messages reach both documents. A frontend-originated
custom message runs once against the shared Python model. A WebAssembly preview
creates another Python object and model registry in Pyodide. Its anywidgets
render and interact through that registry. Their trait and custom-message state
remains local to the Pyodide kernel.

Marimo frontend registry access stays inside the `marimo-frontend`
compatibility package. The Studio package consumes a small control endpoint
with `snapshot`, `subscribe`, and batched `apply` operations. A future runtime can opt
into the bridge by exposing the same semantic cell map.

## Server edit-mode interaction

1. A browser opens `/studio/dashboard/` and receives the Studio workspace.
2. The workspace loads Marimo's native editor and `/dashboard/` preview.
3. The preview joins the editor's kernel session as a kiosk consumer.
4. Moving a slider in either document updates the same Marimo UI value.
5. Marimo reruns dependent cells and sends their outputs to both documents.

## WebAssembly edit-mode interaction

1. The workspace keeps the native editor connected to its Python kernel.
2. Studio starts the WebAssembly preview in a hidden frame and runs the
   notebook in a Pyodide worker.
3. Studio connects after both request clients start, subscribes to controls
   that mount later, then sends the editor's current native control values to
   the preview in one kernel request.
4. Selecting **WebAssembly** reveals the prepared frame.
5. Moving a native control in either pane sends the translated value to the
   other kernel.
6. Each kernel reruns its own dependent cells and updates its own document.
7. `mo.query_params()` changes enter the other runtime through its kernel
   queue, so filter updates keep both panes on the same query state.

Run mode uses the configured presentation runtime. The deployed command
remains a Marimo command:

```console
uv run --with marimo-studio marimo run analysis.py --sandbox --headless
```

The server runtime creates an isolated kernel session for each browser. The
WebAssembly runtime creates an isolated Pyodide worker in each browser. A
standalone view has no editor peer, so its runtime state remains local to that
document.
