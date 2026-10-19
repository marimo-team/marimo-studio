---
title: Deploy a live Python view
description: Serve a Studio view with authentication, a managed process, a reverse proxy, and health checks.
---

# Deploy a live Python view

A live Python view runs notebook code on the server for each marimo session,
with access to the notebook's files, packages, databases, network, and
credentials. Deploy it like any application with that access.

## Start an authenticated process

Store the marimo token in a file readable by the application user:

```console
uvx --with marimo-studio marimo run /srv/analysis/analysis.py \
  --sandbox \
  --headless \
  --host 127.0.0.1 \
  --port 8000 \
  --token-password-file /run/secrets/marimo-token
```

`--host 127.0.0.1` keeps the process behind the local reverse proxy, and the
token protects the marimo and Studio routes. Keep the token file outside the
repository and rotate it through the deployment secret manager.

`--sandbox` installs the notebook's
[PEP 723](https://peps.python.org/pep-0723/) dependencies with
[uv](https://docs.astral.sh/uv/). It does not isolate untrusted notebook code.
Build the environment ahead of time when startup cannot reach package indexes
or policy requires a reviewed lock and image.

Studio writes view build state to marimo's `__marimo__/` folder beside the
notebook, or to `MARIMO_STUDIO_STATE_DIR` when set. Keep the views folder
writable too, for Studio's `.owners/` records and `.locks/` files. See
[Build state location](../reference/configuration.md#build-state-location).

## Put a reverse proxy in front

Terminate [TLS](https://developer.mozilla.org/en-US/docs/Glossary/TLS) at the
proxy, forward HTTP and
[WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)
connections so live notebook and Studio updates arrive, and restrict the upstream port to
trusted local or private-network clients. Studio builds every URL from the
requested path, so the proxy may rewrite `Host`.

### Serve beneath a path prefix

Studio writes every URL relative to the requested URL, so the notebook can live
beneath a prefix such as `https://example.com/occupancy/`. Set marimo's base
URL by how the proxy forwards the prefix:

| Proxy forwards `https://example.com/occupancy/studio/` as | Proxies that do this                                                                                                                                                                                                                       | marimo option           |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------- |
| `/occupancy/studio/`                                      | `/proxy/absolute/<port>/` in jupyter-server-proxy, `/absproxy/<port>/` in code-server                                                                                                                                                      | `--base-url /occupancy` |
| `/studio/`                                                | `/s/<session>/p/<port>/` in [Posit Workbench](https://docs.posit.co/ide/server-pro/), `/proxy/<port>/` in [jupyter-server-proxy](https://jupyter-server-proxy.readthedocs.io/) and [code-server](https://coder.com/docs/code-server/guide) | No base URL             |

When the proxy keeps the prefix, add `--base-url /occupancy` to the command in
[Start an authenticated process](#start-an-authenticated-process).

Browsers resolve relative references against the requested directory, so open
the public root with a trailing slash and have the proxy redirect
`https://example.com/occupancy` to `https://example.com/occupancy/`.

marimo's password form submits to the server root, which a stripping proxy does
not forward. Open the notebook once with `?access_token=<token>` instead, and
Studio redirects beneath the prefix to drop the token, in edit and run mode.
Access logs can record that first query string, so redact `access_token` from
proxy and server logs. `--no-token` also works, but lets every account on the
machine reach the notebook through its local port. Keep a token on shared
hosts.

Pass `--allow-origins` when browser clients send requests from another origin,
and list only origins that should receive notebook sessions.

## Embed the Studio edit workspace

Set `MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS` to the exact HTTP or HTTPS origins,
comma-separated, of parent pages that may frame Studio's edit workspace:

```console
MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS=http://localhost:55021,https://notebooks.example.com \
  uvx --with marimo-studio marimo edit /srv/analysis/analysis.py --sandbox --headless --port 8000
```

Studio adds them to the
[`frame-ancestors`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors)
Content Security Policy directive of the workspace and native editor. An
invalid value stops server startup. See
[Process settings](../reference/configuration.md#process-settings) for limits.

Allow a parent origin only when you trust its pages to present Studio controls.
An allowed parent can position the authenticated workspace inside its own
interface and attempt clickjacking, where a user is misled into interacting with
the framed application. marimo authentication still applies. marimo token
sessions use `SameSite=Lax` cookies, so for a same-site parent on another
origin, authenticate on the Studio origin before loading the frame. A
cross-site parent needs an external authentication layer designed for
third-party iframes.

## Run as an ASGI application

[ASGI](https://asgi.readthedocs.io/en/latest/) is the standard interface
between asynchronous Python web applications and servers. Serve Studio's ASGI
entry point with the notebook path in the environment. The server builds the
views, so its environment needs the Studio extras they use: `deno` for React,
Svelte, and Notebook Kit, and `typst` for Typst:

```console
MARIMO_STUDIO_NOTEBOOK=/srv/analysis/analysis.py \
  uvx --with 'marimo-studio[deno,typst]' uvicorn marimo_studio.asgi:app \
    --host 127.0.0.1 \
    --port 8000 \
    --lifespan on
```

Or build the application in Python:

```python
from marimo_studio import create_asgi_app

app = create_asgi_app("/srv/analysis/analysis.py")
```

At shutdown, the application lifespan closes notebook sessions, provider
operations, and background tasks. Run one ASGI worker per notebook, because
live session and presentation authority is process-local.

`create_asgi_app()` takes no token. Put it behind an access-controlled reverse
proxy, or inside an application that owns authentication, before you expose it
beyond a trusted network.

When a cookie-authenticated reverse proxy requires Server runtime documents on
the same origin, add `MARIMO_STUDIO_TRUSTED_SERVER_RUNTIME=1` to the
environment of the process that serves Studio, then restart it. The policy
covers the view document, the workspace preview iframe, and the
ASGI application. Set it only when you trust the notebook and authored
view code with the authenticated host, because Server-authored code can then
access host cookies, local storage, the parent document, and same-origin
requests. Browser and Prepared runtimes keep opaque-origin isolation.

## Check readiness and shutdown

Point the process check at marimo's health endpoint, or `/occupancy/health`
for a prefixed deployment. Keep health checks on the trusted side of the proxy:

```console
curl --fail http://127.0.0.1:8000/health
```

Stop the process with its normal termination signal and let the application
lifespan finish. A forced stop can interrupt sessions, builds, and artifact
leases.

After deployment, authenticate, open the default view and one named view,
change a control, reload, and inspect browser diagnostics.
To replay Python sessions across reloads, see
[Navigate and preserve state](navigation-and-sessions.md).
