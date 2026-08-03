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
    <strong>The view connects</strong>
    <span>The custom document mounts Marimo's browser runtime and connects to the active kernel session.</span>
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

| Owner          | Responsibility                                                                                                                    |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Marimo         | Python kernels, reactive execution, sessions, authentication, WebSockets, controls, widget models, native APIs, and virtual files |
| Studio server  | View discovery, custom documents, the Studio workspace, projection diagnostics, source editing, and support routes                |
| Studio browser | The authored page shell, view navigation, live source refresh, and hosts for native Marimo outputs                                |

Studio also registers a `marimo.kernel.lifespan` entry point. It adds a
kernel-side reader for the `mo-value` selectors permitted by the active view.
Reads travel through Marimo's kernel command queue and run against that
browser's Python session.

## From a cell to the page

A view starts as an ordinary HTML document with an `#app-shell`. Before
returning it, Studio injects runtime assets, connection metadata, and one
hidden `#marimo-runtime-root` near the end of the document.

The runtime root mounts Marimo's frontend store and providers once. It owns the
WebSocket connection, cell state, UI values, output plugins, and widget
models. `<marimo-cell name="revenue_chart">` resolves the configured alias to
a live Marimo cell, then a React portal renders that cell's native output into
the element. Tables, controls, downloads, and anywidgets keep their Marimo
behavior because Studio projects the native output instead of translating it
to server-rendered HTML.

`mo-value="report.updated_at"` follows a smaller path. The browser requests an
allowed selector from Studio's support route. The kernel reader resolves it
under Marimo's globals lock and returns a JSON-compatible value for the host
element.

HTML and CSS edits refresh the authored shell around the runtime root. The
kernel connection and widget models remain mounted while HTMX swaps the
`#app-shell`. Notebook edits continue through Marimo's reactive scheduler.

## One edit-mode interaction

1. A browser opens `/studio/dashboard/` and receives the Studio workspace.
2. The workspace loads Marimo's native editor and `/dashboard/` preview.
3. The preview joins the editor's kernel session as a kiosk consumer.
4. Moving a slider in either document updates the same Marimo UI value.
5. Marimo reruns dependent cells and sends their outputs to both documents.

Run mode uses the same integration with an isolated kernel session for each
browser. The deployed command remains a Marimo command:

```console
uv run --with marimo-studio marimo run analysis.py --sandbox --headless
```

Studio views are server-backed. Their controls and outputs stay connected to
the live Python kernel that Marimo serves.
