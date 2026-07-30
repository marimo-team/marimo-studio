# Deploy

Marimo serves the notebook and every named view from one ASGI process.

## Validate the notebook

Run the runtime check before deployment:

```console
uvx marimo-studio check analysis.py --runtime
```

The command executes projected cells and resolves the value selectors used by
the configured views.

## Start Marimo

Install Marimo Studio into the command environment and let Marimo prepare the
notebook's PEP 723 dependencies:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

The default view is available at `/`. A view named `executive` is available at
`/executive/`.

Marimo continues to own authentication, WebSockets, kernel APIs, virtual
files, health checks, and notebook assets. The installed Marimo Studio entry
points discover the notebook configuration and present its views.

For a lockfile-managed project, install the locked environment and run Marimo
from it:

```console
uv sync --frozen
uv run marimo run analysis.py \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

Use Marimo's token options when the process is exposed directly:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000 \
  --token-password-file /run/secrets/marimo-token
```

Run `uv run marimo run --help` for CORS, session TTL, watch mode, and other
server options.

## Serve beneath a proxy path

Marimo's `--base-url` defines the public path:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --base-url /proxy/workspace-42
```

The presentation derives scripts, styles, fragments, runtime configuration,
and the WebSocket connection from that path. A reverse proxy should forward
the complete path.

Templates use relative support URLs:

```html
<link
  rel="stylesheet"
  href="./_marimo-studio/views/dashboard/static/app.css"
>
```

## Preserve a session across reloads

Set `preserve_session = true` when a manual run-mode page refresh should
reconnect to the current kernel:

```toml
[tool.marimo-studio]
default = "dashboard"
preserve_session = true
```

The session remains available while Marimo retains it in the serving process.
The deployment must route the reconnect to that process.

## Run in Marimo Hub

Add `marimo-studio` to the workspace dependencies and keep the notebook's
`__marimo__/studio/` source with the workspace. Hub can launch its regular
`marimo run` process. The installed middleware activates at the exposed
notebook URL.

## Process model

Marimo stores browser kernel sessions in the serving process. Use one worker
for a standalone deployment. A multi-process platform needs sticky routing
that returns each browser to its owning worker.
