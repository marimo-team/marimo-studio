---
title: Deploy a live Python view
description: Serve a Studio view with authentication, a managed process, a reverse proxy, and health checks.
---

# Deploy a live Python view

A live Python view runs notebook code on the server for each Marimo session.
Deploy it with the same care as an application that can read the notebook's
files, packages, databases, network, and credentials.

## Start an authenticated process

Store the Marimo token in a file readable by the application user:

```console
uv run --with marimo-studio marimo run /srv/analysis/analysis.py \
  --sandbox \
  --headless \
  --host 127.0.0.1 \
  --port 8000 \
  --token-password-file /run/secrets/marimo-token
```

Binding to `127.0.0.1` keeps the process behind the local reverse proxy. The
token protects the Marimo and Studio routes with session-based authentication.
Keep the token file outside the repository and rotate it through the deployment
secret manager.

`--sandbox` installs the notebook's
[PEP 723](https://peps.python.org/pep-0723/) dependencies with
[uv](https://docs.astral.sh/uv/). It manages the Python environment and does
not isolate untrusted notebook code. Build the environment ahead of time when
startup cannot depend on package indexes or when production policy requires a
reviewed lock and image.

## Put a reverse proxy in front

A reverse proxy accepts public requests, applies access and transport policy,
then forwards them to the Studio process. Terminate
[TLS](https://developer.mozilla.org/en-US/docs/Glossary/TLS), which encrypts the
public connection, at the proxy. Forward HTTP plus
[WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)
connections so live notebook updates continue to work. Preserve the original
host and scheme. Restrict the upstream port to trusted local or private-network
clients.

When the public URL includes a path prefix, pass the same value to Marimo:

```console
marimo run /srv/analysis/analysis.py \
  --headless \
  --host 127.0.0.1 \
  --port 8000 \
  --base-url /occupancy \
  --token-password-file /run/secrets/marimo-token
```

The proxy must forward `/occupancy/` to that process without stripping the
configured public path inconsistently.

Use `--allow-origins` when browser clients must connect from another explicit
origin. Keep the list to origins that should receive notebook sessions.

## Embed the Studio edit workspace

Set `MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS` when another site embeds Studio's edit
workspace. The value is a comma-separated list of exact HTTP or HTTPS origins:

```console
MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS=http://localhost:55021,https://notebooks.example.com \
  marimo edit /srv/analysis/analysis.py --headless --port 8000
```

Studio adds these origins to the
[`frame-ancestors`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors)
Content Security Policy directive on the workspace and native editor documents.
`'self'` remains present for Studio's internal editor iframe. Studio normalizes
host casing, default ports, and an optional trailing slash, then removes
duplicates. The configuration accepts at most 32 origin entries and 4,096
UTF-8 bytes. An invalid or oversized value stops server startup and names the
rejected setting.

Allow a parent origin only when you trust its pages to present Studio controls.
An allowed parent can position the authenticated workspace inside its own
interface and attempt clickjacking, where a user is misled into interacting with
the framed application. The allowlist changes framing policy. Marimo
authentication remains required. Marimo token sessions use `SameSite=Lax`
cookies. For a same-site parent on another origin, authenticate on the Studio
origin before loading the workspace in the frame. A cross-site parent needs an
external authentication layer designed for third-party iframe contexts.

This setting controls which parent documents may frame Studio. Marimo's
`--allow-origins` option controls request origins for browser clients.

## Run as an ASGI application

[ASGI](https://asgi.readthedocs.io/en/latest/) is the standard interface
between asynchronous Python web applications and servers. Studio exposes an
environment-configured ASGI entry point:

```console
MARIMO_STUDIO_NOTEBOOK=/srv/analysis/analysis.py \
  uvicorn marimo_studio.asgi:app \
    --host 127.0.0.1 \
    --port 8000 \
    --lifespan on
```

The equivalent Python API is:

```python
from marimo_studio import create_asgi_app

app = create_asgi_app("/srv/analysis/analysis.py")
```

The application lifespan opens Studio services and closes notebook sessions,
provider operations, and background tasks during shutdown. Start with one ASGI
worker for one notebook application because live session and presentation
authority is process-local.

`create_asgi_app()` has no token configuration argument. Put this form behind
an access-controlled reverse proxy or compose it into an application that owns
authentication before exposing it beyond a trusted network.

## Check readiness and shutdown

Use the Marimo health endpoint for the process check:

```console
curl --fail http://127.0.0.1:8000/health
```

For a prefixed deployment, request `/occupancy/health`. Keep health checks on
the trusted side of the proxy.

Send the process its normal termination signal and allow the application
lifespan to finish. A forced stop can interrupt sessions, builds, and artifact
leases.

After deployment, open the default and one named view, authenticate, change a
notebook control, reload the page, and inspect browser diagnostics. Use
[Navigate and preserve state](navigation-and-sessions.md) when the deployment
must replay Python sessions across reloads.
