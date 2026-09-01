---
title: Create your first view
description: Create a web view from a saved Marimo notebook and place one reactive result inside it.
---

# Create your first view

Start with Python 3.10 through 3.14, `uv`, and a saved Marimo notebook such as
`analysis.py`. Preview the first view's writes:

```console
uvx --from marimo-studio==0.1.0 marimo-studio view create dashboard --target analysis.py --dry-run
```

Create the view after reviewing the plan:

```console
uvx --from marimo-studio==0.1.0 marimo-studio view create dashboard --target analysis.py
```

Studio writes the view beside the notebook:

```text
analysis.py
__marimo__/studio/analysis/
  .gitignore
  .owners/
    dashboard.toml
  dashboard/
    view.toml
    index.html
```

The first creation can update the notebook's PEP 723 Python requirement, pin the
installed Studio version, choose the default view, and add cell aliases. It also
creates the view project, durable owner record, and workspace ignore rules shown
in the plan.

The default starter begins in `index.html`. Keep its CSS and JavaScript inline,
or reference local `.css`, `.js`, and `.mjs` files directly from that document.
View creation prints the exact launch command for Studio and every configured
provider. For the default 0.1.0 view, open the authoring workspace with:

```console
uvx --with marimo-studio==0.1.0 marimo edit analysis.py --sandbox
```

Choose **Develop** to work with the notebook, view source, and rendered preview
in one session.

## Place one result

Give the producing notebook cell a semantic name:

```python
@app.cell
def sales_summary():
    import marimo as mo

    summary = mo.md("## Revenue is on target")
    summary
    return (summary,)
```

Place that complete cell inside `#app-shell` in the view:

```html
<main id="app-shell">
  <marimo-cell name="sales_summary"></marimo-cell>
</main>
```

Save `index.html`. Preview renders **Revenue is on target**. A later notebook
run updates the view through Marimo reactivity. A failed frontend build keeps
the last successful preview available and reports the source problem.

## Run the view

Start the notebook as an application:

```console
uvx --with marimo-studio==0.1.0 marimo run analysis.py --sandbox
```

The default view opens at `/`. Each additional view uses its name as a route.

The [Rio athletes example](../examples/athletes.md) develops the same contract
into three finished views. Continue with [complete cells, rendered objects, and
browser values](notebook-results.md) when the view needs more than one result.
Use [Troubleshoot Studio](troubleshooting.md) when Studio cannot discover the
view, build its source, or connect a notebook result.
