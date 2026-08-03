# Design a view

Choose the notebook behavior an audience needs, then arrange it in HTML and
CSS. Keep calculations and interactive components in the notebook. Use the
view for page structure, wording, navigation, and visual design.

## Arrange the workspace

Studio keeps three surfaces active:

- **Notebook** runs the native Marimo editor.
- **Source** edits `index.html` and `app.css`.
- **Preview** renders the selected view against the notebook kernel.

The notebook and preview start side by side. Open **Pane** to add another
surface on any side, swap two panes, or close a pane. Drag a divider to resize
a split. Use **Layout** to equalize splits or restore the default. **Focus**
fills the workspace with one pane until you press Escape.

Studio remembers the pane arrangement and source tab for each view in the
current browser.

## Choose a projection

| Page content                                         | Element            |
| ---------------------------------------------------- | ------------------ |
| A control, plot, table, download, or anywidget       | `<marimo-cell>`    |
| A date, count, label, or other JSON-compatible value | `mo-value`         |
| Detail loaded after a user action                    | An HTMX cell route |

Add formatting, slicing, or other presentation calculations as small notebook
cells. The view references their displayed output or returned value.

## Place a complete cell output

Use a native cell name or an alias created with `marimo-studio bind`:

```html
<section aria-labelledby="revenue-title">
  <h2 id="revenue-title">Revenue</h2>
  <marimo-cell name="revenue_chart"></marimo-cell>
</section>
```

Marimo renders the cell with its output plugins and widget clients. Controls,
tables, plots, downloads, and anywidgets remain connected to the current
Python session. A cell name can appear once in each view.

## Place a Python value

Use `mo-value` for a JSON-compatible value from a notebook cell:

```html
<time mo-value="report.updated_at"></time>
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

A selector starts with a notebook variable. It can continue through mappings,
attributes, lists, and item keys. Strings, numbers, and booleans render as
text. Objects and arrays render as compact JSON. A `null` leaf renders as empty
text.

Keep expressions in Python:

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

## Structure the document

Each `index.html` is a complete document with one `#app-shell`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Revenue dashboard</title>
    <link rel="stylesheet" href="./_marimo-studio/views/dashboard/static/app.css" />
  </head>
  <body>
    <main id="app-shell">
      <h1>Revenue dashboard</h1>
      <marimo-cell name="revenue_chart"></marimo-cell>
    </main>
  </body>
</html>
```

Place every cell and value host inside `#app-shell`. Studio replaces that shell
when HTML changes and reloads CSS independently.

Serve images and other view files through the scoped static route:

```html
<img src="./_marimo-studio/views/dashboard/static/logo.svg" alt="Acme logo" />
```

Relative support URLs continue to work beneath a configured Marimo base path.

## Reveal detail with HTMX

[HTMX](https://htmx.org/) is available as `window.htmx`. Load a secondary cell
after a user action:

```html
<button
  type="button"
  hx-get="./_marimo-studio/views/dashboard/cells/detail_table"
  hx-target="#details"
>
  Show details
</button>
<section id="details" aria-live="polite"></section>
```

The response inserts a `<marimo-cell>` host that attaches to the current
Marimo session.

## Reserve loading space

Cells and values show skeletons before their first content arrives. Give
charts, tables, and other substantial regions a realistic height:

```css
marimo-cell[name="revenue_chart"] {
  --marimo-cell-skeleton-height: 28rem;
  --marimo-cell-skeleton-color: rgb(20 24 32 / 9%);
  --marimo-cell-skeleton-radius: 0.35rem;
}

time[mo-value] {
  --marimo-value-skeleton-width: 12ch;
}
```

The browser remembers the rendered cell height for the same view and viewport
class. Set `data-skeleton="none"` when an empty first-load region is
intentional.

## Match outputs to the page

Set the page color scheme so Marimo controls use the matching theme:

```css
:root {
  color-scheme: light;
}
```

Mounted output inherits the surrounding font and color. The
`--marimo-cell-*` properties control surfaces, borders, spacing, and accents.
[Loading and theming](reference.md#loading-and-theming) lists the available
properties.

## Repair a projection

Saving the notebook refreshes every open view against the current cell graph.
If a view references a deleted cell or variable, the healthy page regions stay
active. The affected projection shows a compact message, and Studio reports
the source location and repair action.

Restore the notebook definition, update `index.html`, or bind the anonymous
cell again. Then validate the view:

```console
uvx marimo-studio check analysis.py --view dashboard --runtime
```

Agents can request structured results:

```console
uvx marimo-studio check analysis.py \
  --view dashboard \
  --runtime \
  --format json \
  --diagnostics jsonl
```

Browser automation can wait for the current view:

```js
await window.marimoStudio.ready();
const diagnostics = window.marimoStudio.diagnostics();
```

[Browser readiness](reference.md#browser-readiness) defines the state and
event contract.
