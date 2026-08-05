# Share a view

Run a Studio view through Marimo when the audience needs live controls, Python
calculations, or widgets. Marimo executes the notebook and owns each browser's
kernel session.

## Check the view

Run the runtime check in the environment you plan to serve:

```console
uvx marimo-studio check analysis.py --runtime
```

The check executes projected cells and reads referenced Python values. It can
perform any file, network, database, or data access used by those cells.

## Run the default view

Install Studio into the command environment and start Marimo:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

The configured default view is available at `/`. A view named `report` is
available at `/report/`.

Each browser receives an isolated Marimo run session. Controls, widgets,
downloads, and reactive updates use that browser's Python kernel.

## Run Python in the browser

Enable Marimo's WebAssembly runtime for a view that can execute in Pyodide:

```toml
[tool.marimo-studio]
default = "dashboard"
runtime = "wasm"
runtimes = ["server", "wasm"]
```

The default URL now runs the notebook in the browser. Add `?runtime=server` to
select the server runtime for that browser. With `runtime = "server"`, use
`?runtime=wasm` for the browser runtime. Studio removes this parameter before
Marimo initializes `mo.query_params()`.

WebAssembly clients receive the notebook source and install its compatible
PEP 723 dependencies in Pyodide. Keep credentials and server-only code out of
a view configured for this runtime.

## Export a static site

Export one view as a directory that can run from a static host:

```console
uvx marimo-studio export analysis.py \
  --view dashboard \
  --output dist/dashboard
python -m http.server --directory dist/dashboard
```

Open the URL printed by the HTTP server. The page loads the custom view, starts
the notebook in a Pyodide worker, and renders Marimo cells, controls, tables,
plots, `mo-value` projections, and anywidgets through the same browser runtime
used by Studio's WebAssembly preview.

The output includes the selected view files, Studio's browser assets, the
notebook's `public/` directory, and static cell fragments used by HTMX. Upload
the complete output directory to a static host. Pass `--force` to replace an
existing export.

The notebook source ships with the site. Its PEP 723 dependencies must install
in Pyodide, and browser clients must be able to fetch any external data the
notebook reads. Keep credentials and private source out of a static export.

## Protect a public endpoint

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

The file contains the token used to open the app. Run `marimo run --help` in
the deployment environment for CORS, session lifetime, and other server
settings.

## Run from a locked project

When `pyproject.toml` and `uv.lock` own the environment, include
`marimo-studio` in the project dependencies and run Marimo from the lock:

```console
uv sync --frozen
uv run marimo run analysis.py \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

Marimo discovers the Studio extension when the process starts.

## Serve beneath a proxy path

Set Marimo's public path with `--base-url`:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --base-url /proxy/workspace-42
```

Forward the complete path through the reverse proxy. Scripts, styles, cell
requests, value reads, and the kernel connection resolve from that base URL.

Keep support URLs relative in view templates:

```html
<link rel="stylesheet" href="./_marimo-studio/views/dashboard/static/app.css" />
```

## Preserve a session across refreshes

Enable session preservation when a manual server-runtime refresh should
return the browser to its current run-mode kernel:

```toml
[tool.marimo-studio]
default = "dashboard"
preserve_session = true
```

The session remains available while the serving Marimo process retains it.
Route reconnecting requests to that same process.

## Run in Marimo Hub

Add `marimo-studio` to the workspace dependencies and keep
`__marimo__/studio/` with the notebook. Launch the regular `marimo run`
process. The configured view opens at the notebook URL.

## Choose a process model

Marimo stores browser kernel sessions in the serving process. Use one worker
for a standalone deployment. A platform with several workers needs sticky
routing so each browser returns to the process that owns its session.
