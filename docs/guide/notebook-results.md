---
title: Use notebook results
description: Include complete cell output, render one Python object through Marimo, or read a JSON-compatible value in the browser.
---

# Use notebook results

A Studio view projects notebook results through three primitives. Choose the
primitive from the result the page needs.

| Need                                               | Projection                    |
| -------------------------------------------------- | ----------------------------- |
| Include everything a cell produced                 | `<marimo-cell name="...">`    |
| Render one Python object through Marimo            | `<marimo-output value="...">` |
| Read a JSON-compatible value in HTML or JavaScript | `mo-value="..."`              |

Keep calculations, formatting, slicing, and data selection in notebook cells.
The view then selects named cells or variable references from the reactive
graph.

## Include complete cell output <Badge type="info" text="marimo-cell" />

Use a native cell name or an alias created with `marimo-studio bind`:

```html
<section aria-labelledby="analysis-title">
  <h2 id="analysis-title">Analysis</h2>
  <marimo-cell name="analysis"></marimo-cell>
</section>
```

`<marimo-cell>` includes the complete output produced by the cell. It works for
a final expression and for imperative output such as:

```python
@app.cell
def _(mo):
    for index in range(10):
        mo.output.append(index)
```

Marimo mounts the result through its output plugins and widget clients.
Controls, plots, tables, downloads, and anywidgets stay connected to the
selected runtime. Standard output and standard error appear when
`show_cell_logs` is enabled in the notebook configuration.

Each cell name can appear once in a view. Bind an unnamed cell with the
zero-based index reported by `inspect`:

```console
uvx marimo-studio inspect analysis.py --display
uvx marimo-studio bind analysis.py --cell 4 --as analysis
```

## Render one Python object <Badge type="tip" text="marimo-output" />

Use `<marimo-output>` when the page needs Marimo to format a variable as if it
were the displayed expression of a notebook cell:

```html
<section aria-labelledby="dataset-title">
  <h2 id="dataset-title">Dataset</h2>
  <marimo-output value="df"></marimo-output>
</section>
```

The `value` accepts a root variable or a nested selection:

```html
<marimo-output value="report.figure"></marimo-output>
<marimo-output value="results[0]"></marimo-output>
```

Marimo selects the MIME formatter and mounts the result through its native
output area. A DataFrame becomes the native data table. Markdown, plots,
controls, downloads, and widgets retain their regular behavior.

The defining notebook cell remains the reactive owner. During a rerun, the
current output stays visible in a stale state until its replacement is ready.
Each rich-output selector can appear once in a view.

## Read a JSON-compatible value <Badge type="info" text="mo-value" />

Add `mo-value` to the HTML element that should receive a Python value:

```html
<time mo-value="report.updated_at"></time>
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

A reference starts with one notebook variable. It can continue through mapping
keys, attributes, list indexes, and item keys. Strings, numbers, and booleans
render as text. Objects and arrays render as compact JSON. JSON `null` renders
as empty text while remaining available to browser code as `null`.

Define presentation values in a small notebook cell:

```python
@app.cell
def _(df):
    report = {
        "updated_at": f"{df['Date'].max():%d %b %Y}",
        "rows": len(df),
    }
    return (report,)
```

Several small value cells let unrelated reactive branches update
independently.

## Choose between rich output and browser data

`<marimo-output>` asks Marimo to choose a renderer for the selected object.
Use it for a native table, plot, Markdown object, control, download, or widget.

`mo-value` serializes the selected value as JSON. Use it for labels, counts,
lists, configuration objects, or structured data consumed by browser code.

## Reserve loading space

Give substantial projections a realistic first-load size:

```css
marimo-cell[name="analysis"] {
  --marimo-cell-skeleton-height: 28rem;
}

marimo-output[value="df"] {
  --marimo-cell-skeleton-height: 24rem;
}

time[mo-value] {
  --marimo-value-skeleton-width: 12ch;
}
```

Mounted outputs inherit the surrounding font and color. The
`--marimo-cell-*` properties control output surfaces, borders, spacing, fonts,
and accents.

## Check the projections

Run a static check while authoring:

```console
uvx marimo-studio check analysis.py --view dashboard
```

Execute projected cells and resolve projected values before sharing:

```console
uvx marimo-studio check analysis.py --view dashboard --runtime
```

::: warning Runtime checks execute notebook code
The runtime check executes notebook code. It can perform the same file,
network, database, and data access as the projected cells.
:::

Use the [view document reference](../reference/view-document.md) for selector
grammar, states, events, readiness, and diagnostics. Continue with
[Use HTML, CSS, and JavaScript](web-platform.md) to connect JSON-compatible
values to browser behavior.
