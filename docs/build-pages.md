# Build a view

Keep calculations in the notebook. Arrange their outputs in
`__marimo__/studio/<notebook>/<view>/index.html` and style them with files in
the same view folder.

## Define the view shell

Each template is a complete HTML document with one `#app-shell`:

```html
<body>
  <main id="app-shell">
    <!-- Authored application markup -->
  </main>
</body>
```

Cell and value hosts belong inside this shell. Studio replaces the shell when
HTML changes. The browser runtime stays mounted outside it and keeps the
current Marimo session connected.

## Mount a cell

Use `<marimo-cell>` for a complete displayed output:

```html
<section aria-labelledby="revenue-title">
  <h2 id="revenue-title">Revenue</h2>
  <marimo-cell class="chart-cell" name="revenue_chart"></marimo-cell>
</section>
```

`name` accepts a native Marimo cell name or an alias recorded with `bind`. A
cell name can appear once in each view.

Marimo renders through its regular output plugins and model clients. Controls,
tables, plots, downloads, and [anywidgets](https://anywidget.dev/) remain
connected to the current Python session.

## Project a kernel value

Use `mo-value` for a JSON-compatible value that belongs in semantic HTML:

```html
<time mo-value="report.updated_at"></time>
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

A selector starts with one notebook variable and continues through:

- `.name` for a mapping key or Python attribute
- `[0]` for a non-negative item index
- `["key.with.dots"]` for a JSON string item key

The root variable must have one defining cell. The kernel resolves the full
selector and serializes the selected leaf. Intermediate objects stay in
Python.

Strings, numbers, and booleans render as text. `null` renders as empty text.
Objects and arrays render as compact JSON.

Put formatting, arithmetic, slicing, and function calls in a notebook cell:

```python
@app.cell
def _(df):
    report = {
        "updated_at": f"{df['Date'].max():%d %b %Y}",
        "rows": len(df),
    }
    return (report,)
```

Several small context cells keep unrelated reactive branches independent.
Each view references the values it needs.

## Load a cell through HTMX

The view-scoped cell route returns a fresh host:

```html
<button
  type="button"
  hx-get="./_marimo-studio/views/dashboard/cells/detail_table"
  hx-target="#details"
  hx-swap="innerHTML"
>
  Show details
</button>
<section id="details"></section>
```

The inserted host attaches to the existing browser runtime and kernel session.
The HTTP request returns markup. Marimo remains responsible for notebook
execution and cache decisions.

[HTMX](https://htmx.org/) is available as `window.htmx`. Standard HTMX
attributes work throughout `#app-shell`.

## Serve view files

Files in one view folder are available through its scoped static route:

```html
<link
  rel="stylesheet"
  href="./_marimo-studio/views/dashboard/static/app.css"
>
<img
  src="./_marimo-studio/views/dashboard/static/logo.svg"
  alt="Company"
>
```

Relative URLs follow Marimo's configured base path.

## Reserve loading space

Cell hosts show a skeleton before their first output. Give substantial outputs
a realistic height:

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

The configured height remains the host's minimum block size while an output
plugin mounts. The runtime also caches measured heights by view path and
viewport class for later remounts.

Set `data-skeleton="none"` on a cell host whose empty first-load region is
intentional:

```html
<marimo-cell name="status" data-skeleton="none"></marimo-cell>
```

## Theme mounted output

Set the page color scheme so Marimo controls use the matching theme:

```css
:root {
  color-scheme: dark;
}
```

Mounted outputs inherit the surrounding font and color. CSS custom properties
control their surfaces and accents:

```css
.chart-cell {
  --marimo-cell-font: Inter, ui-sans-serif, system-ui, sans-serif;
  --marimo-cell-background: transparent;
  --marimo-cell-foreground: #202124;
  --marimo-cell-surface: #fff;
  --marimo-cell-muted: #f3f3f1;
  --marimo-cell-muted-foreground: #66645f;
  --marimo-cell-border-color: #d8d7d2;
  --marimo-cell-accent: #315f82;
  --marimo-cell-radius: 0.25rem;
  --marimo-cell-padding: 0;
}
```

Application CSS owns layout, spacing, borders, and responsive behavior around
the projected output.

## Observe readiness

Cell hosts publish:

```text
connecting | loading | stale | ready | missing | error
```

Value hosts publish:

```text
connecting | loading | stale | ready | error
```

Both use `data-state`. Pending hosts also use `aria-busy="true"`.

Wait for the current hosts:

```js
await window.marimoStudio.ready();
```

The root `<html>` element exposes combined state through
`data-marimo-studio-state`. The document dispatches
`marimo-studio:runtime-ready` and `marimo-studio:idle`.

Cell hosts dispatch `marimo-cell-ready`, `marimo-cell-updated`, and
`marimo-cell-error`. Value hosts dispatch `marimo-value-updated` and
`marimo-value-error`.

Retained stale content counts as settled for page readiness.
