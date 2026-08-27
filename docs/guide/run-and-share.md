---
title: Run, export, and share
description: Serve published Studio artifacts through Marimo or export a compatible production artifact as a static WebAssembly site.
---

# Run, export, and share

Studio serves a validated artifact from each selected view project. Choose the
runtime from the notebook's dependencies, data access, and hosting
environment.

| Destination    | Runtime            | Result                                                                                    |
| -------------- | ------------------ | ----------------------------------------------------------------------------------------- |
| Python server  | Server             | Marimo executes the notebook in one isolated kernel per browser                           |
| Browser client | WebAssembly        | Pyodide executes the notebook in one worker per browser                                   |
| Static host    | WebAssembly export | A directory contains the production artifact, notebook source, and browser runtime assets |

## Build the delivery artifact

Build the production profile for the selected view:

```console
uv run marimo-studio view build analysis.py \
  --name dashboard \
  --profile production
```

Studio builds and validates the production files before publishing them. A
failed build leaves the last published page available.

Run the notebook check in the environment you plan to serve:

```console
uv run marimo-studio validate analysis.py --view dashboard --level runtime
```

The runtime check starts the complete notebook reactive app in an isolated
process, then checks the selected view's projected cells, rendered outputs, and
JSON-compatible values. Notebook startup can perform its usual file, network,
database, and data access.

## Serve through Marimo <Badge type="info" text="Server" />

Start the configured notebook with Marimo:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --host 127.0.0.1 \
  --port 8000
```

Install the dependencies required by every selected view provider in the
serving environment.

The default view opens at `/`. A view named `report` opens at `/report/`.
Each browser receives an isolated Marimo run session, so its controls, widgets,
downloads, and reactive updates use that browser's Python kernel.

Each response binds the selected view files to one saved notebook revision and
runtime configuration. Notebook or view edits create another presentation
revision, so mounted results cannot mix files from different saves.

Check the authenticated workspace lifecycle at `/_marimo-studio/status`:

```json
{
  "schema": 1,
  "state": "ready",
  "default_view": "dashboard",
  "views": ["dashboard"]
}
```

`state` is `needs-view` while a configured notebook awaits its first view and
`error` when Studio cannot materialize the workspace. Run-mode document
requests return a structured repair response for both states.

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
`marimo run --help` in the deployment environment for current cross-origin,
session, and server options.

### Run from a locked project

Pin Studio and each frontend extension. Commit `uv.lock`, then start Marimo
from the locked environment:

```console
uv sync --frozen
uv run marimo run analysis.py \
  --headless \
  --host 127.0.0.1 \
  --port 8000
```

Marimo discovers Studio and its installed frontend extensions when the process
starts.

### Serve beneath a proxy path

Set Marimo's public path with `--base-url`:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --base-url /proxy/workspace-42
```

Forward the complete path through the reverse proxy. Artifact documents carry
a revision-qualified base, so relative styles, modules, images, fonts, workers,
and data requests stay within the selected browser tree.

::: details Preserve a server session across refreshes

Enable session preservation when a manual Server refresh should return the
browser to its current run-mode kernel:

```toml [pyproject.toml]
[tool.marimo-studio]
default = "dashboard"
preserve_session = true
```

Studio reconnects when the canonical public notebook query matches the query
that created the kernel. Private Studio routing and transport keys do not
affect the match. A different public query starts a fresh kernel and
presentation.

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
select the Server runtime for one browser. With `runtime = "server"`, use
`?runtime=wasm` for the browser runtime.

WebAssembly clients receive the notebook source, compatible PEP 723
dependencies, and the target records required by the selected view. Marimo
executes each required notebook cell in the browser worker and attaches the
rendered result to its mounted host.

::: warning Browser clients receive notebook source
Keep credentials and server-side secrets out of a WebAssembly view. The
browser also needs network access to each external dataset the notebook reads.
:::

## Export a static site <Badge type="warning" text="Public source" />

The exported directory includes the saved notebook source. Review it before
publishing the directory.

Export one view, then serve the generated directory over HTTP:

```console
uv run marimo-studio export analysis.py \
  --view dashboard \
  --output dist/dashboard
python -m http.server --bind 127.0.0.1 --directory dist/dashboard
```

Export builds or reuses the view's production artifact. The generated page
starts the notebook in a Pyodide worker and mounts the artifact's projection
hosts. The output includes:

- Validated public files from the production artifact
- Saved notebook source and its browser runtime configuration
- Studio browser assets
- Files from the notebook's `public/` directory

The export command prints the exact entrypoint. A provider can return a nested
document such as `pages/index.html`, which Studio publishes with its scripts,
styles, images, and other relative assets at the same artifact-relative paths.
Upload the complete directory and configure the static host to serve the
reported entrypoint. Use `--force` after reviewing an existing output directory
that should be replaced.

::: warning Review the public export boundary
The exported notebook source is public to site visitors. Its dependencies must
install in Pyodide, and external data must be reachable from the browser.
Named Iconify icons also load from the Iconify API unless the view uses inline
SVG.
:::

[Notebook configuration](../reference/configuration.md) defines runtime
defaults. [CLI reference](../reference/cli.md#export) defines export options
and exit behavior. [Runtime behavior](../reference/runtimes.md) compares
execution, session, and projection-resolution contracts.
