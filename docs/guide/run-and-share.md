---
title: Run or publish a view
description: Studio views use a Python or WebAssembly runtime. The WebAssembly runtime can also be packaged as a static site.
---

# Run or publish a view

A Studio view can use one of two notebook runtimes:

| Studio menu | Configuration | Notebook execution                                                                                               |
| ----------- | ------------- | ---------------------------------------------------------------------------------------------------------------- |
| **Python**  | `server`      | Isolated server-side session with access to local files, databases, credentials, native packages, and anywidgets |
| **Browser** | `wasm`        | Pyodide worker whose packages and data sources must be reachable from the visitor's browser                      |

When both runtimes are configured, Studio can change the active runtime and
keep the view source fixed.

Runtime and delivery are separate choices. `marimo run` serves a live view.
`marimo-studio view export` packages the Browser runtime as a static directory.

## Run with Python

`marimo-studio status --target analysis.py --json` prepares configured provider
requirements from saved notebook or project metadata before loading providers.
`uv` may resolve and install packages during that step. The resulting
`launch_requirements` field contains the exact Studio and provider environment
for `marimo run`.

Review `view.toml` and the saved Python dependencies before running `status`
against an unfamiliar project. Pass each launch requirement to `uv run` through
`--with`. A notebook whose only provider is the default 0.1.0 Vanilla provider
runs with:

```console
uv run --with marimo-studio==0.1.0 marimo run analysis.py \
  --sandbox \
  --headless \
  --host 127.0.0.1 \
  --port 8000
```

The default view opens at `/`. A view named `report` opens at `/report/`.

Use Marimo token settings when other clients can reach the process:

```console
uv run --with marimo-studio==0.1.0 marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000 \
  --token-password-file /run/secrets/marimo-token
```

Use Marimo `--base-url` when a reverse proxy serves the notebook beneath a
path.

## Run with WebAssembly

Configure browser execution for notebooks whose dependencies and data sources
work in Pyodide:

```toml
[tool.marimo-studio]
default = "dashboard"
runtime = "wasm"
runtimes = ["server", "wasm"]
```

The default URL starts the notebook in a browser worker. Add
`?runtime=server` to use the Python session when the configuration permits it.

::: warning Browser visitors receive notebook source
The browser receives the saved notebook, compatible dependencies, and public
files. Keep credentials and server-owned code out of browser execution. Each
external dataset must be reachable from the visitor's browser.
:::

## Export a static site

A static export packages the WebAssembly runtime, saved notebook source, and
view files into one directory:

```console
marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard
```

Serve the complete output directory over HTTP:

```console
python -m http.server --bind 127.0.0.1 --directory dist/dashboard
```

The export uses document-relative runtime and asset URLs. Upload the directory
without rewriting its HTML.

Place views that link to one another in sibling directories:

```text
dist/athletes/
  overview/
    index.html
  explorer/
    index.html
```

A link from `overview` to `../explorer/index.html` now works at the domain root,
beneath a repository base path, and after moving the complete `athletes`
directory.

::: warning Review the export before publishing
The export contains the saved notebook source and files from the notebook's
`public/` directory. Its dependencies must install in Pyodide, and external
data must be reachable from the browser.
:::

Host static exports on a dedicated origin. Authored JavaScript, notebook code,
widgets, and rendered outputs run with that origin's browser authority.

The Browser runtime fetches Pyodide and versioned Marimo runtime metadata over
the network. Allow the required worker, script, connection, and package origins
in the hosting content security policy. Static exports are not offline bundles.

Studio caps the complete browser runtime payload at 16 MiB of UTF-8 JSON.
Notebook source and broad projection declarations are common contributors. When
Studio reports `runtime-config-too-large`, use finite projection targets or
reduce the saved notebook source before exporting again.

Use `--force` after reviewing an existing destination that should be replaced.

## Export the analytical notebook

Create a static record of the notebook with its code and captured outputs:

```console
mkdir -p dist/notebook
marimo export html analysis.py \
  --sandbox \
  --output dist/notebook/index.html
```

This export presents the analytical document as it ran during the build. Use a
WebAssembly view when a visitor should change a control and recompute dependent
cells in the browser.

Each family in the [live example catalog](../examples/index.md) pairs this
static notebook document with the WebAssembly views produced by
`marimo-studio view export`.
