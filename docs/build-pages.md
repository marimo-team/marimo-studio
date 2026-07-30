# Design a view

Choose the notebook behavior an audience needs, then build the page around it.
Keep calculations and interactive components in the notebook. Put layout,
wording, navigation, and visual design in the view.

## Choose what to place in the page

| Need | Use |
| --- | --- |
| A complete control, plot, table, download, or anywidget | `<marimo-cell>` |
| A date, count, label, or other JSON-compatible value | `mo-value` |
| A large detail region that should appear on demand | An HTMX cell route |
| New formatting or derived presentation data | A small notebook cell |

Start with existing notebook outputs. Add presentation-specific Python when
the page needs a value the notebook does not yet expose cleanly.

## Place a complete notebook output

Use `<marimo-cell>` with a native cell name or an alias created by `bind`:

```html
<section aria-labelledby="revenue-title">
  <h2 id="revenue-title">Revenue</h2>
  <marimo-cell class="chart-cell" name="revenue_chart"></marimo-cell>
</section>
```

Marimo renders the cell through the same output plugins and model clients used
by its native interface. Controls, tables, plots, downloads, and
[anywidgets](https://anywidget.dev/) remain connected to the current Python
session.

Each cell name can appear once in a view. Reuse the same name in another view
when both audiences need that output.

## Place a Python value in page text

Use `mo-value` when the page needs one value rather than a complete cell:

```html
<dl>
  <div>
    <dt>Last updated</dt>
    <dd><time mo-value="report.updated_at"></time></dd>
  </div>
  <div>
    <dt>Selected records</dt>
    <dd><strong mo-value="selection.count"></strong></dd>
  </div>
</dl>
```

A selector starts with one notebook variable and can continue through:

- `.name` for a mapping key or Python attribute
- `[0]` for a non-negative item index
- `["key.with.dots"]` for a JSON string item key

```html
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

The root variable must have one defining cell. The selected leaf renders
strings, numbers, and booleans as text. Objects and arrays render as compact
JSON. A `null` value renders as empty text.

Keep arithmetic, formatting, slicing, and function calls in Python:

```python
@app.cell
def _(df):
    report = {
        "updated_at": f"{df['Date'].max():%d %b %Y}",
        "rows": len(df),
    }
    return (report,)
```

The variable can be a dictionary, a list, a scalar, or another value with a
JSON-compatible selected leaf. Several small context cells let unrelated
reactive branches update independently.

## Structure the view as an ordinary web page

Each `index.html` is a complete HTML document with one `#app-shell`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Revenue dashboard</title>
    <link
      rel="stylesheet"
      href="./_marimo-studio/views/dashboard/static/app.css"
    >
  </head>
  <body>
    <main id="app-shell">
      <h1>Revenue dashboard</h1>
      <marimo-cell name="revenue_chart"></marimo-cell>
    </main>
  </body>
</html>
```

Place every `<marimo-cell>` and `mo-value` inside `#app-shell`. Saving HTML
replaces this shell, while CSS reloads independently. Your preview keeps its
current kernel and widget models.

Files in the view folder use the view's scoped static route:

```html
<img
  src="./_marimo-studio/views/dashboard/static/logo.svg"
  alt="Acme logo"
>
```

Relative URLs continue to work when Marimo serves beneath a configured base
path.

## Reveal detail on demand

[HTMX](https://htmx.org/) is available as `window.htmx`. A view can request a
fresh cell element when the audience asks for more detail:

```html
<button
  type="button"
  hx-get="./_marimo-studio/views/dashboard/cells/detail_table"
  hx-target="#details"
  hx-swap="innerHTML"
>
  Show details
</button>
<section id="details" aria-live="polite"></section>
```

The response inserts `<marimo-cell name="detail_table">` into `#details`. The
cell connects to the current Marimo session, so the page keeps its controls,
widget models, and reactive state.

Use this pattern for secondary tables, diagnostics, and other regions that do
not need to occupy the initial page.

## Keep the layout steady while cells load

Each cell shows a skeleton before its first output arrives. Reserve a realistic
height for charts, tables, and other substantial regions:

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

The cell keeps that minimum height while its output plugin mounts. After a
successful render, the browser remembers the measured height for the same view
and viewport class.

Use `data-skeleton="none"` when an empty first-load region is intentional:

```html
<marimo-cell name="status" data-skeleton="none"></marimo-cell>
```

## Match notebook output to the page

Set the page color scheme so Marimo controls choose a matching theme:

```css
:root {
  color-scheme: light;
}
```

Mounted output inherits the surrounding font and color. Use Studio's CSS
properties to align its surfaces and accents:

```css
.chart-cell {
  --marimo-cell-font: Inter, ui-sans-serif, system-ui, sans-serif;
  --marimo-cell-background: transparent;
  --marimo-cell-foreground: #202124;
  --marimo-cell-surface: #fff;
  --marimo-cell-muted: #f3f3f1;
  --marimo-cell-border-color: #d8d7d2;
  --marimo-cell-accent: #315f82;
  --marimo-cell-radius: 0.25rem;
  --marimo-cell-padding: 0;
}
```

Application CSS owns the layout, spacing, borders, and responsive behavior
around the output. See [Loading and theming](reference.md#loading-and-theming)
for the complete property list.

## Build a second experience from the same notebook

Add another view when an audience needs different results or page structure:

```console
uvx marimo-studio view add operations analysis.py
uvx marimo-studio analysis.py --view operations
```

The `operations` view receives its own HTML, CSS, and static files. It reuses
the notebook's cells and aliases.

## Wait for a settled view in browser automation

Cell and value elements expose their current state through `data-state`.
Browser tests and agents can wait until the current view settles:

```js
await window.marimoStudio.ready();
```

The promise resolves when every current cell and value has rendered content,
retained content while updating, or reached a terminal error. See
[Browser readiness](reference.md#browser-readiness) for state and event names.

Run a runtime check before sharing the view:

```console
uvx marimo-studio check analysis.py --view operations --runtime
```
