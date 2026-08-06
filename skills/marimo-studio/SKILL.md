---
name: marimo-studio
description: >-
  Design, build, repair, validate, serve, and export audience-specific Marimo
  Studio views backed by existing Marimo notebooks. Use when an agent needs to
  inspect notebook cells, create or edit named views, project live cells or
  JSON-compatible Python values into HTML, add browser behavior, maintain
  several views from one notebook, or prepare a view for sharing.
---

# Build Marimo Studio views

Turn a Marimo notebook into a focused page by arranging its existing outputs
and values. Keep computation, reactive state, controls, and data access in the
notebook. Keep page structure, wording, styling, and browser interactions in
the Studio view.

Use this workflow:

1. Inspect the notebook and its views.
2. Create or select one named view.
3. Choose the smallest set of cell and value projections for the audience.
4. Compose the page in `index.html`, `app.css`, and optional relative assets.
5. Develop beside the live notebook in `marimo edit`.
6. Run static checks, then runtime checks.
7. Serve through `marimo run` or export the selected view.

## Preserve the source of truth

- Keep notebook cell bodies unchanged unless the user requests notebook work.
- Use `marimo-studio view add` to create views and managed configuration.
- Use native Marimo cell names when available. Bind anonymous cells through
  `marimo-studio bind`.
- Treat existing view files as authored source. Read them completely before
  changing their structure or visual language.
- Preserve working projections and relative asset paths unless the requested
  design replaces them.
- Keep the Server runtime selected during ordinary development. Exercise the
  WebAssembly runtime when the user requests it or the view will be exported.

`view add` may update the notebook's managed PEP 723 metadata. `bind` records a
stable cell alias there. Both commands preserve notebook cell bodies.

## 1. Inspect the notebook

List the configured views and inspect cells that display an output:

```console
marimo-studio view list analysis.py --format json
marimo-studio inspect analysis.py --display --format json
```

Use the JSON fields to identify:

- the default and available views
- native cell names
- zero-based cell indexes
- source locations
- definitions and dependencies
- cells with a displayed result

Add `--include-code` when the preview and definitions do not explain a cell's
purpose. Use `--limit` for an initial pass through a large notebook.

Inspect runtime values and output MIME types when the static graph leaves a
content decision unresolved:

```console
marimo-studio inspect analysis.py \
  --display \
  --runtime \
  --format json \
  --diagnostics jsonl
```

Runtime inspection executes notebook code and can perform its configured file,
network, database, and data access. Start with static inspection.

## 2. Create or select a view

Create one view for one audience or task:

```console
marimo-studio view add dashboard analysis.py --format json
```

View names start with a lowercase letter and contain lowercase letters,
numbers, or hyphens. A new view starts with every notebook cell in source order
and assigns stable aliases to anonymous cells.

The authored files live beside the notebook:

```text
__marimo__/studio/analysis/dashboard/
  index.html
  app.css
```

Files referenced by `index.html` may live in the same directory or its nested
folders. Use relative URLs for modules, images, fonts, and other view assets.

For several audiences, create several views from the same notebook:

```console
marimo-studio view add report analysis.py --format json
marimo-studio view add operations analysis.py --format json
```

Share notebook computation and cell aliases across views. Give each view its
own content hierarchy, language, and visual emphasis.

## 3. Plan the page around the audience

Before editing, write down four decisions:

1. Who will use the view?
2. What question or action should the first screen support?
3. Which notebook outputs answer that question?
4. Which details can follow later in the reading order?

Choose projections by their rendered contract:

| Need                                                   | Projection                 |
| ------------------------------------------------------ | -------------------------- |
| Control, plot, table, download, markdown, or anywidget | `<marimo-cell name="...">` |
| JSON-compatible label, number, date, list, or mapping  | An element with `mo-value` |

Use a native cell name directly:

```html
<marimo-cell name="revenue_chart"></marimo-cell>
```

Bind an anonymous cell when the view needs a stable name:

```console
marimo-studio bind revenue-chart analysis.py \
  --cell 4 \
  --format json
```

The index is zero-based and comes from `inspect`. Reinspect before using
`--overwrite` when a changed notebook makes a binding stale or ambiguous.
Render each cell name once in a view.

## 4. Compose the view

Write one complete HTML document with one `#app-shell`. Keep every projection
inside that shell:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Quarterly performance</title>
    <link rel="stylesheet" href="app.css" />
  </head>
  <body>
    <main id="app-shell" class="studio-view grid gap-6 lg:grid-cols-2">
      <header class="lg:col-span-2">
        <p class="studio-eyebrow">Quarterly review</p>
        <h1 class="text-4xl font-semibold tracking-tight">Performance at a glance</h1>
      </header>

      <section class="studio-card p-5" aria-labelledby="trend-title">
        <h2 id="trend-title" class="text-lg font-semibold">Revenue trend</h2>
        <marimo-cell class="trend" name="revenue_chart"></marimo-cell>
      </section>

      <section class="studio-card p-5" aria-labelledby="summary-title">
        <h2 id="summary-title" class="text-lg font-semibold">Summary</h2>
        <strong mo-value="report.total"></strong>
      </section>
    </main>
  </body>
</html>
```

Studio supplies responsive layout, spacing, typography, color, border, and
state utilities in class attributes. Its stable shortcuts are `studio-view`,
`studio-card`, `studio-button`, and `studio-eyebrow`.

Build a semantic reading order before adding visual surfaces. Keep headings
hierarchical, label controls, preserve keyboard focus, and let wide tables and
plots shrink or scroll inside their section. Use cards for repeated records or
clear tool boundaries.

## 5. Project Python values

`mo-value` starts with a notebook variable and can traverse mappings,
attributes, lists, and item keys:

```html
<time mo-value="report.updated_at"></time>
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

Put formatting, arithmetic, slicing, calls, and comprehensions in a notebook
cell when notebook changes are in scope. Keep the view selector declarative.

Use a hidden value host when a browser module needs typed data:

```html
<span id="report-data" hidden mo-value="report"></span>
<output id="report-total"></output>
<script type="module" src="app.js"></script>
```

Register the listener before reading the current snapshot:

```js
const source = document.querySelector("#report-data");
const total = document.querySelector("#report-total");

const render = (value) => {
  total.textContent = value.total;
};

source.addEventListener("marimo-value-updated", (event) => {
  render(event.detail.value);
});

if (source.marimoValue !== undefined) {
  render(source.marimoValue);
}
```

`marimoValue` contains the current JSON-compatible value. `undefined` means a
value has not arrived or the selector is unavailable. JSON `null` remains a
value. The cached snapshot stays available while the host is loading or stale.

Listen for `marimo-value-error` when the component needs a local fallback. Use
`window.marimoStudio.ready()` when an operation depends on every current cell
and value reaching a settled state.

## 6. Style loading and rendered outputs

Keep the semantic theme variables at the top of `app.css`. Put page-specific
selectors under `/* APP */`. Preserve the starter `marimo-cell` variable
mapping so notebook outputs inherit the page typography, surfaces, and accent
color.

Support light and dark appearance through the existing theme tokens. Prefer
borders and spacing for structure. Keep color roles semantic and use one
restrained interaction color.

Reserve realistic first-load space for substantial outputs:

```css
marimo-cell.trend {
  --marimo-cell-skeleton-height: 28rem;
}

time[mo-value] {
  --marimo-value-skeleton-width: 12ch;
}
```

Set cell padding, border, radius, and background through the provided
`--marimo-cell-*` variables when the surrounding page already owns the visual
container.

## 7. Develop with Marimo

Open the notebook in edit mode:

```console
marimo edit analysis.py --sandbox
```

Marimo opens the Studio workspace with the notebook and selected view. Use
**Build** for the notebook and preview together. Open **HTML & CSS** when the
view source should share the workspace. Source changes saved from Studio or an
external editor stay synchronized with `index.html` and `app.css` on disk.

CSS saves update the current page styles. HTML changes replace the authored
shell around the mounted runtime. A module change reloads the view document so
its imports and initialization follow the regular page lifecycle.

Keep the Server runtime selected while developing against the editor kernel.
Confirm that controls, tables, plots, downloads, and anywidgets remain
interactive after source edits and view switches.

## 8. Validate and repair

Run static validation after each coherent view edit:

```console
marimo-studio check analysis.py \
  --view dashboard \
  --format json \
  --diagnostics jsonl
```

Run the runtime check before sharing:

```console
marimo-studio check analysis.py \
  --view dashboard \
  --runtime \
  --format json \
  --diagnostics jsonl
```

Use each diagnostic's `view`, `target`, source location, and `hint` as the
repair queue. Apply the smallest source change, then rerun the same check.

| Diagnostic               | Repair                                                    |
| ------------------------ | --------------------------------------------------------- |
| Missing cell             | Use a current native name or bind the intended cell index |
| Stale or ambiguous alias | Reinspect the notebook, then bind with `--overwrite`      |
| Unknown value selector   | Correct the root variable or selector path                |
| Runtime value failure    | Inspect the defining cell and its current output          |
| Workspace needs a view   | Open Studio and create the configured default view        |

Inspect the running Studio preview after the checks pass:

- The first screen supports the named audience and task.
- Every projected cell and value settles successfully.
- Controls, tables, plots, downloads, and anywidgets remain interactive.
- Notebook changes update the dependent view content.
- Source edits refresh while current notebook state remains intact.
- Loading skeletons prevent disruptive layout shifts.
- The layout remains readable at narrow and wide widths.
- Light and dark appearance preserve readable contrast.
- Keyboard focus and accessible labels remain visible.
- Browser modules initialize and respond after a document reload.

## 9. Serve or export

Serve every configured view through Marimo:

```console
marimo run analysis.py --sandbox --headless
```

The configured default view is available at `/`. A view named `report` is
available at `/report/`. Each browser receives its own Marimo run session.

Export a view when its notebook supports the WebAssembly runtime:

```console
marimo-studio export analysis.py \
  --view report \
  --output dist/report \
  --format json \
  --diagnostics jsonl
```

Run the runtime check before export. Use `--force` after reviewing an existing
output directory that should be replaced. Treat the exported directory as
generated output and make later revisions in the notebook or view source.

## Handoff

Report:

- the notebook and view names
- the audience and primary task
- the view files changed
- the projected cell names and value selectors
- any managed metadata or notebook changes
- the static and runtime check results
- the interaction, responsive layout, theme, and loading states inspected

Leave the notebook and every view in a runnable, checked state.
