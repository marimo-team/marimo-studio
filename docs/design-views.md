# Design a view

Choose the notebook behavior an audience needs, then arrange it in HTML and
CSS. Keep calculations and interactive components in the notebook. Use the
view for page structure, wording, navigation, and visual design.

## Arrange the workspace

The toolbar controls the main canvas:

- **Notebook** opens the native Marimo editor.
- **Build** places the native Marimo editor beside the selected view.
- **Preview** fills the canvas with the selected view.

Open **HTML & CSS** from the workspace menu to place `index.html`, `theme.css`,
or `app.css` beside the live preview.

Open the toolbar's workspace menu when a task needs another arrangement.
Choose **Open saved layout**, then **Arrange panes** to add a surface on
any side, swap two panes, or close a pane. Drag a divider to resize a split.
**Equalize split sizes** restores even proportions.

Studio keeps the notebook, source editors, and preview mounted while you move
between task modes and custom arrangements. It remembers the mode, custom
arrangement, split sizes, and source tab for each view in the current browser.
Choosing a view from the toolbar opens **Build**. Links between authored
views preserve the current mode.

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

## Style the view

Write Wind4 utilities directly in `index.html`. Studio generates the matching
CSS in the browser when the document loads and when HTMX inserts a fragment:

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
and covers Tailwind-style layout, spacing, typography, color, borders,
responsive variants, and state variants. Studio also defines four stable
shortcuts:

- `studio-view` provides a centered responsive page width and padding.
- `studio-card` provides a semantic bordered surface.
- `studio-button` provides a compact interactive control.
- `studio-eyebrow` provides a small uppercase section label.

Edit `theme.css` for shared semantic tokens. The file is loaded automatically
between Studio's foundation and `app.css`:

```css
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
`rounded-lg` read these variables. The starter theme maps them into projected
Marimo outputs through its `marimo-cell` block. Keep that mapping when changing
the palette. Put named components and view-specific selectors in `app.css`.
Its rules load last.

`iconify-icon` accepts the same Iconify names as `mo.icon()`. Add
`aria-hidden="true"` to decorative icons. An icon that carries meaning needs
`role="img"` and an `aria-label`. Icon data loads from Iconify's service when
first requested.

## Inspect the complete examples

The repository includes two view-authoring patterns:

- `examples/analysis.py` is a compact dashboard. Its HTML uses responsive
  utilities, icons, and arbitrary properties for projected-cell loading space.
  Its theme defines the semantic palette, keeping the complete layout readable
  from `index.html`.
- `examples/nga_collection.py` is a three-view research workflow. **Corpus**,
  **Study**, and **Packet** apply different themes and page structures to the
  same filters, selection order, notebook outputs, and download.

Open either notebook in Studio, change a native control, then edit a utility
class or theme token. Saving the view source replaces the authored shell after
its utility CSS is ready. Mounted cells and their widget models move into the
new shell with their current state.

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

Set the page color scheme in `theme.css` so Marimo controls use the matching
theme:

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
