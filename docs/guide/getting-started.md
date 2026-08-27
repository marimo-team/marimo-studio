---
title: Getting started
description: Create, build, and validate a custom view for a saved Marimo notebook.
---

# Getting started

Start with a saved Marimo notebook:

```console
uvx marimo-studio view create analysis.py --name dashboard
```

The first view records Studio configuration, the selected provider
requirement, and managed view metadata in the notebook's PEP 723 block. For a
notebook owned by a Python project, add `marimo-studio` and any provider extra
through that project's dependency workflow before creating the view.

The default starter creates:

```text
__marimo__/studio/analysis/
  .gitignore
  dashboard/
    view.toml
    index.html
```

Open the notebook:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Choose **Develop** to see notebook code, frontend source, and the rendered view
together.

## Mount a notebook result

Give a producing Marimo cell a name:

```python
@app.cell
def summary_table(data):
    table = data.group_by("category").len()
    table
    return (table,)
```

Add the cell to `index.html` inside `#app-shell`:

```html
<marimo-cell name="summary_table"></marimo-cell>
```

Build the view after editing:

```console
uvx marimo-studio view build analysis.py --name dashboard
```

The build publishes generated files beneath `.artifacts/`. If a later build
fails, Source shows the diagnostic and the previous valid page stays available.

## Validate

```console
uvx marimo-studio validate analysis.py --view dashboard --level static
uvx marimo-studio validate analysis.py --view dashboard --level runtime
```

Runtime validation starts the complete reactive notebook in an isolated
process and can perform its configured file, network, database, and data
access. Studio then checks the selected projected results.

Browser validation uses the active Studio server and selected client:

```console
uvx marimo-studio validate analysis.py --view dashboard \
  --level browser \
  --server http://localhost:2718
```

## Run the view

```console
uvx --with marimo-studio marimo run analysis.py --sandbox
```

The default view is served at `/`. Named views have their own routes.

[Frontend authoring](authoring-options.md) covers custom toolchains.
[Notebook results](notebook-results.md) covers cells, outputs, values, and
controls.
