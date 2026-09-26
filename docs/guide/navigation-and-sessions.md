---
title: Navigate and preserve state
description: Link named views, synchronize public query parameters, use fragments, and control Python session replay.
---

# Navigate and preserve state

Each named view has a stable route. The configured default opens at `/`. A view
named `report` opens at `/report/`.

Studio keeps public query parameters and the URL fragment with the active
presentation while removing private routing and credential parameters from
notebook query state.

## Link named views

Use sibling-relative links when a group of views should work under a live
server, a deployment base path, and a copied static export:

```html
<nav aria-label="Analysis views">
  <a href="../dashboard/index.html">Dashboard</a>
  <a href="../report/index.html">Report</a>
</nav>
```

Export linked views into sibling directories:

```text
dist/analysis/
  dashboard/
    index.html
  report/
    index.html
```

Studio carries the active public query and fragment through an in-product view
switch. An authored link controls its own destination URL.

## Read and write public query parameters

Use `mo.query_params()` in the notebook:

```python
@app.cell
def filters(mo):
    query = mo.query_params()
    region = query.get("region", "all")
    return (region,)
```

Open the view with a public parameter:

```text
/report/?region=emea
```

Changes made through `mo.query_params()` synchronize with Preview and browser
history. Repeated keys and blank values remain distinct:

```text
/?tag=first&tag=second&empty=
```

Studio keeps routing keys such as `runtime`, `session_id`, access tokens, and
its `marimo_studio_*` capabilities out of the public notebook query.

## Use fragments for local navigation

An anchor stays inside the current view:

```html
<a href="#error-evidence">Review errors</a>

<section id="error-evidence">...</section>
```

Studio applies the fragment after the presentation is ready. Browser back and
forward navigation restores the public query, fragment, and selected view.

## Choose runtime from the URL

When both runtimes are configured, `runtime` selects the notebook runtime for
the request:

```text
/?runtime=wasm
/?runtime=server
```

The parameter must name one of the configured `runtimes`. Studio treats it as
routing state, so notebook code does not receive it through
`mo.query_params()`.

## Open multiple tabs

In edit mode, Studio uses [marimo's native sessions](https://docs.marimo.io/).
Tabs opened on the same notebook and server share one Python kernel. Changing
a control recomputes notebook outputs across Python previews. Widget state and
public query parameters synchronize across those tabs. Each Studio tab keeps
its selected view.

marimo gives the first connection editing control. Other tabs can interact
with the notebook through its kiosk view. Select **Take over** in the embedded
editor to move editing control to that tab. Closing the editor tab leaves the
remaining tabs connected to the same kernel.

Run mode follows marimo's visitor sessions. The Browser runtime runs a separate
notebook in each browser worker. Selecting another runtime changes which
notebook instance supplies that tab's outputs.

## Preserve a Python session across navigation

Enable session replay in the notebook configuration:

```toml
[tool.marimo-studio]
runtime = "server"
runtimes = ["server", "wasm"]
preserve_session = true
```

In run mode, Studio can reconnect a navigation or reload to the existing
Python runtime session when all of these still match:

- saved notebook
- Python runtime
- view path and public query
- current server process and live session

A different public query starts or selects the session for that query. A
missing, expired, or mismatched session starts a fresh one. The Browser runtime
manages its notebook instance in the visitor's browser and does not use
`preserve_session`.

Leave `preserve_session = false` when each reload should receive a fresh Python
session. Continue with [Run or export a view](run-and-share.md) to choose a
runtime and delivery path.
