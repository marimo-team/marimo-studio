---
title: Run, export, and share
description: Serve Studio views through Marimo or export a compatible notebook as a static WebAssembly site.
---

# Run, export, and share

Studio uses Marimo's application server for finished views. Choose the runtime
from the notebook's dependencies, data access, and hosting environment.

| Destination    | Runtime            | Result                                                                     |
| -------------- | ------------------ | -------------------------------------------------------------------------- |
| Python server  | Server             | Marimo executes the notebook in one isolated kernel per browser            |
| Browser client | WebAssembly        | Pyodide executes the notebook in one worker per browser                    |
| Static host    | WebAssembly export | A directory contains the view, notebook source, and browser runtime assets |

## Check the deployed path

Run the check in the environment you plan to serve:

```console
uvx marimo-studio check analysis.py --runtime
```

The check executes projected cells and reads referenced Python values. It can
perform their file, network, database, and data access.

## Serve through Marimo <Badge type="info" text="Server" />

Start the configured notebook with Marimo:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

The default view opens at `/`. A view named `report` opens at `/report/`.
Each browser receives an isolated Marimo run session, so its controls, widgets,
downloads, and reactive updates use that browser's Python kernel.

Check the authenticated workspace lifecycle at `/_marimo-studio/status`:

```json
{
  "schema": 1,
  "state": "ready",
  "default_view": "dashboard",
  "views": ["dashboard"]
}
```

`state` is `needs-view` while a definition awaits its first view and `error`
when configuration cannot materialize a workspace. Run-mode document requests
return a structured repair response in both cases.

::: warning Keep each browser on its kernel process
Use one worker for a standalone deployment. A multi-worker platform needs
sticky routing so each browser returns to the process that owns its kernel.
:::

### Protect the endpoint

Use Marimo's token settings when clients can reach the process directly:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000 \
  --token-password-file /run/secrets/marimo-token
```

The file contains the token required to open the app. Run
`marimo run --help` in the deployment environment for current CORS, session,
and server options.

### Run from a locked project

Add `marimo-studio` to the project dependencies, commit `uv.lock`, and run
Marimo from that environment:

```console
uv sync --frozen
uv run marimo run analysis.py \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

Marimo discovers Studio when the process starts.

### Serve beneath a proxy path

Set Marimo's public path with `--base-url`:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --base-url /proxy/workspace-42
```

Forward the complete path through the reverse proxy. Keep view assets relative
to `index.html` so styles, modules, images, and imports resolve beneath that
base URL.

::: details Preserve a server session across refreshes

Enable session preservation when a manual server-runtime refresh should return
the browser to its current run-mode kernel:

```toml [pyproject.toml]
[tool.marimo-studio]
default = "dashboard"
preserve_session = true
```

The session remains available while the serving Marimo process retains it.
Route reconnecting requests to that process.
:::

## Run the notebook in the browser <Badge type="tip" text="WebAssembly" />

Select the WebAssembly runtime for a notebook whose dependencies and data
sources work in Pyodide:

```toml [pyproject.toml]
[tool.marimo-studio]
default = "dashboard"
runtime = "wasm"
runtimes = ["server", "wasm"]
```

The default URL now runs the notebook in the browser. Add `?runtime=server` to
select the server runtime for one browser. With `runtime = "server"`, use
`?runtime=wasm` for the browser runtime.

WebAssembly clients receive the notebook source and install compatible PEP 723
dependencies in Pyodide.

::: warning Browser clients receive notebook source
Keep credentials and server-side secrets out of a WebAssembly view. The
browser also needs network access to every external dataset the notebook reads.
:::

## Export a static site <Badge type="warning" text="Public source" />

Export one view, then serve the generated directory over HTTP:

```console
uvx marimo-studio export analysis.py \
  --view dashboard \
  --output dist/dashboard
python -m http.server --directory dist/dashboard
```

The page starts the notebook in a Pyodide worker and renders the selected view.
The output contains the view files, notebook source, Studio browser assets,
the notebook's `public/` directory, and static HTMX cell fragments.

Upload the complete directory to the static host. Use `--force` after reviewing
an existing output directory that should be replaced.

::: warning Review the public export boundary
The exported notebook source is public to site visitors. Its dependencies must
install in Pyodide, and external data must be reachable from the browser.
Named Iconify icons also load from the Iconify API unless the view uses inline
SVG.
:::

[Notebook configuration](../reference/configuration.md) defines runtime
defaults. [CLI reference](../reference/cli.md#export) defines export options
and exit behavior. [Runtime behavior](../reference/runtimes.md) compares the
execution and session contracts.
