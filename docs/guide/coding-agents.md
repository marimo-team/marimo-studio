---
title: Work with coding agents
description: Inspect a Marimo notebook, create a view, edit its web files, bind cell references, and validate the result through the agent API.
---

# Work with coding agents

Marimo Studio gives a coding agent a bounded workflow around one saved
notebook. The agent can shape an audience-specific interface while data
transformations, metric definitions, assumptions, and domain rules remain in
notebook cells for a person to inspect and run.

The agent inspects the notebook graph, creates or locates a view, edits
ordinary web files, and checks every projection against the saved notebook.

Use `marimo_studio.agents` from Marimo code mode:

```python
import marimo._code_mode as cm
import marimo_studio.agents as studio

ctx = cm.get_context()
notebook = studio.inspect(ctx, include_code=True)
view = studio.ensure_view(ctx, "dashboard")
```

`studio.inspect` compiles the saved notebook and returns its cells,
definitions, references, source positions, native names, and dependency
relationships. It leaves notebook cells unevaluated.

`studio.ensure_view` creates the named view when needed and returns the current
paths. A new view starts with every notebook cell in source order.

## Inspect before editing

Read the notebook graph and current view files before choosing content:

```python
for cell in notebook.cells:
    print(cell.index, cell.name, cell.definitions, cell.references)

index_html = (view.root / "index.html").read_text()
app_css = (view.root / "app.css").read_text()
```

Use `include_code=True` when cell names and definitions leave the intended
output unclear.

::: tip Keep source ownership clear
Keep data transformations, calculations, metric definitions, and presentation
values in notebook cells. Keep page structure, wording, styles, modules, and
browser behavior in the view files. A new audience can then receive another
view while each analytical definition remains in one notebook.
:::

## Select the projection

Choose the projection from the result the page needs:

```html
<marimo-cell name="analysis"></marimo-cell>
<marimo-output value="revenue_chart"></marimo-output>
<strong mo-value="report.total"></strong>
```

- `<marimo-cell>` includes everything a named cell produced.
- `<marimo-output>` renders one selected Python object through Marimo.
- `mo-value` provides a JSON-compatible value to HTML and JavaScript.

[Use notebook results](notebook-results.md) defines the three projection
forms.

## Bind an unnamed cell

Give an unnamed cell a stable reference with its zero-based notebook position:

```python
binding = studio.bind(ctx, "revenue-chart", 4)
```

Read the current notebook again before setting `overwrite=True` for an
existing alias. The returned binding identifies the selected cell and the
configuration update.

## Edit the web files

Write one complete HTML document with one `#app-shell`. Place every projection
inside that shell. Add CSS, JavaScript modules, images, fonts, and other assets
under `view.root` and reference them with relative URLs.

Read each file immediately before writing it so the edit incorporates changes
from the Studio workspace or another editor. Saved HTML, CSS, and module
changes refresh the live preview.

## Check the result

Validate the saved notebook and every reference in one view:

```python
results = studio.check(ctx, view_name="dashboard")
failures = [result for result in results if result.status == "fail"]
```

Each result has a `pass`, `warn`, or `fail` status and points to the affected
projection or view file. Repair each failing reference, then call
`studio.check` again.

Inspect the live view after the static check passes. Confirm the reading order,
reactive updates, browser behavior, loading states, controls, plots, tables,
downloads, widgets, and narrow and wide layouts.

## Use the terminal workflow

The command-line interface exposes the same inspect, create, bind, and check
operations for agents working outside Marimo code mode:

```console
uvx marimo-studio inspect analysis.py --include-code --format json
uvx marimo-studio view add analysis.py --name dashboard --format json
uvx marimo-studio check analysis.py --view dashboard --format json
uvx marimo-studio check analysis.py --view dashboard --runtime --format json
```

::: warning Runtime checks execute notebook code
`--runtime` executes notebook code and can perform its file, network, database,
and data access. Use it in the notebook environment before serving or
exporting the view.
:::

The [Agent API reference](../reference/agent-api.md) defines signatures,
returns, errors, and side effects. The [CLI reference](../reference/cli.md)
defines machine output and exit codes.
