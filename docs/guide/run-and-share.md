---
title: Run or export a view
description: Run a view with the Python or Browser runtime, or export the Browser runtime as a static directory.
---

# Run or export a view

Runtime chooses where notebook code executes. Delivery chooses how visitors
receive the view.

| Studio menu         | Config ID | Notebook execution                                                                                                                 |
| ------------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **Python runtime**  | `server`  | A Marimo session with server files, databases, credentials, native packages, and [anywidgets](https://anywidget.dev/)              |
| **Browser runtime** | `wasm`    | A [Pyodide](https://pyodide.org/) worker that runs Python through [WebAssembly](https://webassembly.org/) in the visitor's browser |

`marimo run` serves either configured runtime from a live process.
`marimo-studio view export` writes a static Browser runtime directory.

An [anywidget](https://anywidget.dev/) is a custom browser interface connected
to a Python model.

## Configure available runtimes

```toml
[tool.marimo-studio]
default = "dashboard"
runtime = "server"
runtimes = ["server", "wasm"]
```

`runtime` chooses the default. `runtimes` controls the choices shown in Studio
and accepted through `?runtime=`.

Use the Python runtime for native packages, private files, databases, or server
credentials. Use the Browser runtime when the notebook and its data can run in
Pyodide and the visitor should compute locally. Its packages and data sources
must be reachable from that browser.

::: warning Browser visitors receive notebook source
The Browser runtime receives the saved notebook, compatible dependencies, and
public files. Keep credentials and server-owned code in the Python runtime.
Each external dataset must be reachable from the visitor's browser.
:::

## Run a live view locally

Use the launch requirements printed by `view create`. A notebook whose view
uses the default 0.1.0 provider runs with:

```console
uv run --with marimo-studio==0.1.0 marimo run analysis.py \
  --sandbox \
  --headless \
  --host 127.0.0.1 \
  --port 8000
```

The default view opens at `http://127.0.0.1:8000/`. A view named `report`
opens at `http://127.0.0.1:8000/report/`.

Run `marimo-studio status --target analysis.py --json` when a project uses
additional view providers. Its `launch_requirements` list contains the Studio
and provider environment required by `marimo run`. Reviewing status can
resolve, install, and import provider packages declared by the project.

Use [Deploy a live Python view](deploy.md) before exposing the process to other
clients.

## Export a static Browser runtime view

Build and export the production profile:

```console
marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard
```

Serve the complete directory over HTTP:

```console
python -m http.server --bind 127.0.0.1 --directory dist/dashboard
```

Open `http://127.0.0.1:8000/`. The export contains the production artifact,
Browser runtime integration, saved notebook source, and notebook `public/`
files. Upload the complete directory and keep its relative paths intact.

::: warning Review the export before publishing
The notebook source and `public/` files are visible to visitors. Authored
JavaScript, notebook code, widgets, and rendered output execute in the visitor's
browser. Studio places the provider-authored page in a sandboxed iframe with an
opaque origin, so it cannot read the hosting origin's cookies, storage, or
same-origin server data. Origin-sensitive browser APIs and cross-origin requests
observe that opaque origin.
:::

The Browser runtime fetches Pyodide, packages, runtime metadata, and any remote
view dependencies over the network. Allow their script, worker, connection,
font, image, and data origins in the hosting
[Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP).
A static export is a relocatable HTTP directory, not an offline bundle.

Use `--force` after reviewing an existing destination that should be replaced.
Studio stages the export before replacing that directory.

## Export the analytical notebook

Create a static record of notebook code and captured output:

```console
mkdir -p dist/notebook
marimo export html analysis.py \
  --sandbox \
  --output dist/notebook/index.html
```

Use this document when visitors should read the analysis as it ran during the
export. Use a Studio Browser runtime export when they should change controls and
recompute dependent notebook cells.
