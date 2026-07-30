# Share a view

Serve a Studio view with Marimo when the audience needs live controls, Python
calculations, or widgets. Visitors land on the custom page while Marimo runs
the notebook and manages their kernel sessions.

## Check the view against the notebook

Run the runtime check in the environment you plan to deploy:

```console
uvx marimo-studio check analysis.py --runtime
```

The check executes every cell projected by the configured views and reads each
referenced Python value. It can perform the file, network, database, and data
access defined by those notebook cells.

## Start the server

Install Studio into the command environment and run the notebook through
Marimo:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

`--sandbox` prepares the notebook's PEP 723 dependencies. The default Studio
view is available at `/`. A view named `executive` is available at
`/executive/`.

Each browser receives an isolated Marimo run-mode session. Controls, widgets,
downloads, and reactive updates continue to use that session's Python kernel.

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

The file must contain the token used to open the app. Run `marimo run --help`
in the deployment environment for CORS, session lifetime, and other server
settings.

## Use a locked project environment

When `pyproject.toml` and `uv.lock` own the deployment environment, install the
lock and run Marimo from it:

```console
uv sync --frozen
uv run marimo run analysis.py \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

Include `marimo-studio` in the project dependencies so Marimo discovers the
presentation extension when the process starts.

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
<link
  rel="stylesheet"
  href="./_marimo-studio/views/dashboard/static/app.css"
>
```

## Keep a session through a manual refresh

Enable session preservation when a page refresh should return the visitor to
the current kernel:

```toml
[tool.marimo-studio]
default = "dashboard"
preserve_session = true
```

The session remains available while the serving Marimo process retains it.
Route the reconnect to that same process.

## Run in Marimo Hub

Add `marimo-studio` to the workspace dependencies and keep
`__marimo__/studio/` with the notebook. Launch the regular `marimo run`
process in Marimo Hub, then open the configured view at the notebook URL.

## Choose a process model

Marimo stores browser kernel sessions in the serving process. Use one worker
for a standalone deployment. A platform with several workers needs sticky
routing so each browser returns to the process that owns its session.
