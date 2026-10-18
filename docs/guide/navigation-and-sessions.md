---
title: Link views and keep state
description: Link a notebook's views, share state through query parameters and fragments, and reconnect Python sessions across reloads.
---

# Link views and keep state

A notebook's views can work as one site. Each view has a stable URL, so a
dashboard can link to its report, and a link can carry query parameters that
the notebook reads, so the report opens filtered to the region the reader
picked. The default view opens at
`/`, and a view named `report` opens at `/report/`.

## Link views

Use sibling-relative links, so the links keep working under a live server, a
deployment base path, and a copied static export:

```html
<nav aria-label="Analysis views">
  <a href="../dashboard/index.html">Dashboard</a>
  <a href="../report/index.html">Report</a>
</nav>
```

Export linked views into sibling folders, such as `dist/analysis/dashboard/`
and `dist/analysis/report/`.

## Share state in the URL

Read and write query parameters in the notebook with `mo.query_params()`:

```python
@app.cell
def filters(mo):
    query = mo.query_params()
    region = query.get("region", "all")
    return (region,)
```

`/report/?region=emea` then opens the report filtered to EMEA. Changes the
notebook makes through `mo.query_params()` update the browser URL and history.
Repeated keys and blank values stay distinct, as in `?tag=a&tag=b&empty=`.

An anchor such as `<a href="#errors">` stays inside the current view. Studio
applies the fragment once the view is ready, and back and forward restore the
query, the fragment, and the selected view. Switching views in Studio carries
the current query and fragment along.

Studio keeps its own parameters, such as `runtime`, `session_id`, and access
tokens, out of `mo.query_params()`. When a notebook allows both runtimes,
`?runtime=wasm` or `?runtime=server` picks one for the request.

## Open multiple tabs

In `marimo edit`, tabs on the same notebook share one Python kernel. Changing
a control in one tab recomputes results in every Python preview, and widget
state and query parameters sync across tabs. Each tab keeps its own selected
view.

The first tab has editing control. Other tabs can still use the notebook, and
**Take over** in the embedded editor moves editing control to them.

In `marimo run`, each visitor gets their own session. The Browser runtime runs
a separate notebook in each browser.

## Keep a Python session across reloads

By default, a reload in `marimo run` starts a fresh Python session. Turn on
`preserve_session` to reconnect to the existing one:

```toml
[tool.marimo-studio]
preserve_session = true
```

Studio reconnects when the saved notebook, the Python runtime, the view path
and query, and the server process all still match. Anything else starts a new
session, and a different query selects the session for that query. The
Browser runtime ignores this setting.
