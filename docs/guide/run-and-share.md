---
title: Run or publish a page
description: Choose Python, browser execution, or static hosting from the notebook's code, data, and security needs.
---

# Run or publish a page

Choose where the notebook can safely and completely execute:

| Audience environment | Choose it when                                                                                | Result                                                       |
| -------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Python server        | The notebook needs local files, databases, server credentials, native packages, or anywidgets | Each browser receives its own Python-backed notebook session |
| Browser              | The notebook and its data can run in Pyodide and may be sent to the visitor                   | Each browser runs a separate notebook worker                 |
| Static host          | Browser execution works and the page should be deployed as ordinary files                     | An exported directory runs without a Python server           |

Studio calls this execution choice the **runtime**. The page source stays the
same across runtimes.

## Run with Python

Start the notebook through marimo:

```console
uv run --with marimo-studio marimo run analysis.py \
  --sandbox \
  --headless \
  --host 127.0.0.1 \
  --port 8000
```

The default view opens at `/`. A view named `report` opens at `/report/`.
Every browser receives an isolated notebook session for its controls, widgets,
downloads, and reactive updates.

Install the notebook dependencies and the frontend dependencies used by every
served view in this Python environment.

### Protect a reachable server

Use marimo's token settings when clients can reach the process directly:

```console
uv run --with marimo-studio marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000 \
  --token-password-file /run/secrets/marimo-token
```

Use one worker for a standalone deployment. A multi-worker platform needs
sticky routing so each browser returns to the process that owns its notebook
session.

Use marimo's `--base-url` when a reverse proxy serves the notebook beneath a
path:

```console
uv run --with marimo-studio marimo run analysis.py \
  --sandbox \
  --headless \
  --base-url /proxy/workspace-42
```

Forward the complete path through the proxy.

## Run in the browser

Choose browser execution for notebooks whose Python packages and data sources
work in Pyodide:

```toml
[tool.marimo-studio]
default = "dashboard"
runtime = "wasm"
runtimes = ["server", "wasm"]
```

The default URL now starts the notebook in a browser worker. Add
`?runtime=server` to run one browser through Python instead.

::: warning Browser visitors receive notebook source
The browser receives the saved notebook, compatible dependencies, and public
files. Keep credentials and server-only code out of browser execution. Each
external dataset must be reachable from the visitor's browser.
:::

## Export for static hosting

Export one view, then serve the directory over HTTP:

```console
marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard
python -m http.server --bind 127.0.0.1 --directory dist/dashboard
```

The command builds the production page and prints its exact entry file. Upload
the complete directory so scripts, styles, images, fonts, workers, and data
remain at their expected relative paths.

::: warning Review the exported directory before publishing
The export contains the saved notebook source and files from the notebook's
`public/` directory. Its dependencies must install in Pyodide, and its external
data must be reachable from the browser.
:::

Use `--force` after reviewing an existing output directory that should be
replaced.

See [Configuration](../reference/configuration.md) for runtime defaults and
session preservation. See the [CLI reference](../reference/cli.md) for exit
behavior and machine-readable output.
