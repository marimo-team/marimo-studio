---
title: Design a view
description: Project notebook cells and Python values into a responsive web document with live Marimo behavior.
---

# Design a view

Choose the notebook behavior an audience needs, then arrange it in HTML and
CSS. Keep calculations, formatting logic, controls, and interactive outputs in
the notebook. Use the view for page structure, wording, navigation, and visual
design.

## Choose a projection

| Page content                                           | Projection                 |
| ------------------------------------------------------ | -------------------------- |
| Control, plot, table, download, Markdown, or anywidget | `<marimo-cell name="...">` |
| JSON-compatible label, number, date, list, or mapping  | An element with `mo-value` |
| Detail requested after a user action                   | An HTMX cell route         |

Use small notebook cells for presentation calculations such as labels,
formatted dates, summaries, and selected records. This keeps the view
declarative and lets Marimo track each dependency.

## Place a complete cell output

Use a native cell name or an alias created with `marimo-studio bind`:

```html
<section aria-labelledby="revenue-title">
  <h2 id="revenue-title">Revenue</h2>
  <marimo-cell name="revenue_chart"></marimo-cell>
</section>
```

Marimo mounts the cell through its regular output plugins and widget clients.
Controls, plots, tables, downloads, and anywidgets remain connected to the
active runtime. Place a cell name once in each view.

## Place a Python value

Use `mo-value` when the page needs part of a JSON-compatible Python value:

```html
<time mo-value="report.updated_at"></time>
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

A selector starts with one notebook variable. It can continue through mapping
keys, attributes, list indexes, and item keys. Strings, numbers, and booleans
render as text. Objects and arrays render as compact JSON. A JSON `null` leaf
renders as empty text.

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

Several small value cells allow unrelated reactive branches to update
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
    <link rel="stylesheet" href="app.css" />
  </head>
  <body>
    <main id="app-shell" class="studio-view grid gap-6">
      <h1>Revenue dashboard</h1>
      <marimo-cell name="revenue_chart"></marimo-cell>
    </main>
  </body>
</html>
```

Keep every cell and value projection inside `#app-shell`. Studio can then
refresh the authored page while preserving the mounted Marimo runtime.

## Style with utilities and theme tokens

Write Wind4 utilities directly on elements:

```html
<main id="app-shell" class="studio-view grid gap-6 lg:grid-cols-2">
  <section class="studio-card p-5">
    <h2 class="flex items-center gap-2 text-lg font-semibold">
      <iconify-icon icon="lucide:chart-no-axes-combined" aria-hidden="true"></iconify-icon>
      Revenue
    </h2>
    <marimo-cell name="revenue_chart"></marimo-cell>
  </section>
</main>
```

The utility vocabulary follows [UnoCSS Wind4](https://unocss.dev/presets/wind4)
for responsive layout, spacing, typography, color, borders, and state variants.
Studio also provides four shortcuts:

| Class            | Behavior                                          |
| ---------------- | ------------------------------------------------- |
| `studio-view`    | Centered page width with responsive outer padding |
| `studio-card`    | Semantic bordered surface                         |
| `studio-button`  | Compact interactive control                       |
| `studio-eyebrow` | Small uppercase section label                     |

Define the semantic palette near the top of `app.css`:

```css
/* THEME */

:root {
  color-scheme: light dark;
  --background: light-dark(#ffffff, #111713);
  --foreground: light-dark(#17201b, #edf3ef);
  --card: light-dark(#f8faf9, #18201b);
  --card-foreground: var(--foreground);
  --border: light-dark(#dce3df, #344039);
  --primary: light-dark(#0877d1, #3ba7ad);
  --radius: 8px;
}
```

Utilities such as `bg-card`, `text-foreground`, `border-border`, and
`rounded-lg` read these variables. Rules in `app.css` use the regular CSS
cascade and take precedence over generated utilities.

`iconify-icon` accepts the same Iconify names as `mo.icon()`. Decorative icons
use `aria-hidden="true"`. Give an icon that carries meaning `role="img"` and
an `aria-label`. Iconify fetches named icon data from its API when first used.

## Add relative assets and modules

Reference images, modules, fonts, and nested files relative to `index.html`:

```html
<img src="images/logo.svg" alt="Acme" />
<script type="module" src="scripts/app.js"></script>
```

Relative JavaScript imports and CSS `url(...)` references resolve from their
source file. Studio reloads a scripted document after an HTML or module save so
the browser evaluates the module graph through its regular page lifecycle.

## Read a value in JavaScript

Use a hidden `mo-value` host as the typed data source for browser behavior:

```html
<span id="report-data" hidden mo-value="report"></span>
<output id="report-total"></output>
<script type="module" src="app.js"></script>
```

Register the listener before reading the current snapshot in `app.js`:

```js
const source = document.querySelector("#report-data");
const total = document.querySelector("#report-total");

const render = (report) => {
  total.textContent = report.total;
};

source.addEventListener("marimo-value-updated", (event) => {
  render(event.detail.value);
});

if (source.marimoValue !== undefined) {
  render(source.marimoValue);
}
```

`undefined` means the first value has not arrived or the selector is
unavailable. JSON `null` remains a value. Listen for `marimo-value-error` when
the component needs a local fallback.

The [view document reference](view-api.md#browser-value-api) defines property,
event, loading, and readiness behavior.

## Reserve loading space

Give substantial outputs a realistic first-load height:

```css
marimo-cell[name="revenue_chart"] {
  --marimo-cell-skeleton-height: 28rem;
}

time[mo-value] {
  --marimo-value-skeleton-width: 12ch;
}
```

Mounted outputs inherit the surrounding font and color. Use the
`--marimo-cell-*` properties when the view needs to align output surfaces,
borders, spacing, and accents with the page.

## Load detail on demand

[HTMX](https://htmx.org/) is available as `window.htmx`. Request a secondary
cell after a user action:

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

The response inserts a `<marimo-cell>` host connected to the current Marimo
session.

## Check and repair projections

Run a static check while authoring:

```console
uvx marimo-studio check analysis.py --view dashboard
```

Execute projected cells and resolve values before sharing:

```console
uvx marimo-studio check analysis.py --view dashboard --runtime
```

When a notebook edit removes a projected cell or variable, healthy page
regions remain active and the affected host reports its source location and a
repair hint. Restore the notebook definition, update `index.html`, or bind the
intended cell again, then rerun the same check.

Use the [view document reference](view-api.md) for exact states and events.
Use [Examples](examples.md) to inspect complete compact and multi-view designs.
