---
title: Create your first view
description: Create a web view from a saved Marimo notebook and place one reactive result inside it.
---

# Create your first view

Start with a saved Marimo notebook such as `analysis.py`. Create a view for one
job the analysis needs to support:

```console
uvx marimo-studio view create dashboard --target analysis.py
```

Studio writes the view beside the notebook:

```text
analysis.py
__marimo__/studio/analysis/
  .gitignore
  dashboard/
    view.toml
    index.html
```

The default starter keeps the complete frontend in `index.html`. Open the
authoring workspace:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
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
run updates the page through Marimo reactivity. A failed frontend build keeps
the last successful preview available and reports the source problem.

## Run the view

Start the notebook as an application:

```console
uvx --with marimo-studio marimo run analysis.py --sandbox
```

The default view opens at `/`. Each additional view uses its name as a route.

The [Rio athletes example](../examples/athletes.md) develops the same contract
into three finished views. Continue with [complete cells, rendered objects, and
browser values](notebook-results.md) when the page needs more than one result.
