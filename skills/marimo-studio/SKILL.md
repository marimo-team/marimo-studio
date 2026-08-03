---
name: marimo-studio
description: >-
  Build, run, and verify custom server-backed views from a Marimo notebook.
  Use when an agent needs to inspect notebook cells, compose a dashboard or
  tool, project Python values, preserve Marimo controls or anywidgets, work
  beside the live editor, add HTMX interactions, or prepare a view to share.
---

# Marimo Studio

Keep calculations, reactive state, controls, and widgets in the notebook.
Author each view under:

```text
__marimo__/studio/<notebook-stem>/<view>/
  index.html
  app.css
```

Use `marimo-studio` when it is installed. Use `uvx marimo-studio` from another
project. Start the live notebook with Marimo's `edit` and `run` commands.

## 1. Discover the notebook

Inspect displayed cells before choosing page content:

```console
marimo-studio inspect analysis.py --display
```

Use JSON for automation. Add `--runtime` when MIME output or a Python value
affects the design:

```console
marimo-studio inspect analysis.py --display --format json > /tmp/studio-cells.json
marimo-studio inspect analysis.py --display --runtime --format json > /tmp/studio-runtime.json
```

Runtime inspection executes the notebook's file, network, database, and data
access. Check runtime errors before selecting projections. Confirm a failing
notebook in plain Marimo before changing its view.

## 2. Create a view

```console
marimo-studio view add dashboard analysis.py --format json
marimo-studio view list analysis.py --format json
```

The first command adds Studio to the notebook's PEP 723 dependencies when
needed. Preserve notebook code outside that metadata block. The starter view
contains every notebook cell in source order.

Native Marimo cell names work directly. Bind an anonymous cell when the view
needs a stable name:

```console
marimo-studio bind summary analysis.py --cell 4
```

Bindings belong to the notebook and are shared by every view. Reinspect and
bind with `--overwrite` after a bound cell changes meaning or becomes
ambiguous. Ask before adding presentation-specific cells to the notebook.

## 3. Author the document

Write one complete HTML document with one `#app-shell`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Executive summary</title>
    <link rel="stylesheet" href="./_marimo-studio/views/executive/static/app.css" />
  </head>
  <body>
    <main id="app-shell">
      <h1>Performance</h1>
      <marimo-cell name="chart"></marimo-cell>
      <p>Updated <time mo-value="report.updated_at"></time></p>
    </main>
  </body>
</html>
```

Place every cell and value host inside `#app-shell`. Mount a cell name once per
view. `<marimo-cell>` uses Marimo's output plugins and widget models, so
controls, tables, plots, downloads, and anywidgets stay connected to Python.

`mo-value` accepts a root variable followed by attribute, mapping, or item
selection:

```html
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

Keep formatting, arithmetic, calls, comprehensions, and slicing in notebook
cells. Several small context cells let unrelated reactive branches update
independently.

Use view-scoped routes for HTMX and static files:

```html
<button
  type="button"
  hx-get="./_marimo-studio/views/executive/cells/detail_table"
  hx-target="#details"
>
  Show details
</button>
<section id="details"></section>
<img src="./_marimo-studio/views/executive/static/logo.svg" alt="Company" />
```

Link another configured view relative to the document base:

```html
<a href="./report/">Open report</a>
```

Studio handles configured view links as in-place preview switches. Saved HTML
replaces `#app-shell` while the Marimo runtime remains mounted. Initialize
direct event listeners idempotently, or delegate events from `document`.

## 4. Reserve loading space

Give substantial outputs realistic skeleton dimensions:

```css
marimo-cell[name="chart"] {
  --marimo-cell-skeleton-height: 30rem;
}

time[mo-value] {
  --marimo-value-skeleton-width: 12ch;
}
```

Set `color-scheme` and the `--marimo-cell-*` properties to match the view.
Verify first load in a fresh browser session. Use
[`DESIGN.md`](https://github.com/marimo-team/marimo/blob/main/DESIGN.md) when
the project has no visual system.

## 5. Work beside the notebook

```console
uv run --with marimo-studio marimo edit analysis.py --sandbox
```

The authenticated root opens Studio. The default layout places the Marimo
editor beside the live preview. Add the source pane to edit `index.html` and
`app.css` in the browser. External editor changes arrive through the same
source revision flow.

Open another view from the toolbar or at `/studio/<view>/`. View switches and
source refreshes keep the preview runtime, kernel session, controls, and widget
models mounted.

## 6. Validate

Run the selected view through static and runtime checks:

```console
marimo-studio check analysis.py --view dashboard --runtime
```

Use structured output in an agent loop:

```console
marimo-studio check analysis.py \
  --view dashboard \
  --runtime \
  --format json \
  --diagnostics jsonl
```

Repair the reported source location, cell name, binding, or value selector.
Repeat until the command exits with status 0.

## 7. Exercise the browser

Start a token-free local editor on an unused port:

```console
uv run --with marimo-studio \
  marimo edit analysis.py \
  --sandbox \
  --headless \
  --port 8000 \
  --no-token
```

Use `$agent-browser` with a unique session. In the preview iframe:

```js
const frame = document.querySelector("[data-preview-frame]");
await frame.contentWindow.marimoStudio.ready();
frame.contentDocument.documentElement.dataset.marimoStudioState;
```

Verify:

1. Notebook and projected controls stay synchronized.
2. `mo-value` follows the kernel value.
3. Anywidgets and HTMX fragments remain interactive.
4. HTML and CSS edits refresh with the same preview session ID.
5. An invalid template keeps the last valid shell and publishes a diagnostic.
6. The repaired template clears the diagnostic.
7. Loading space, desktop layout, and mobile layout remain stable.
8. The console and network log contain no unexpected errors.

Close the browser session after collecting evidence.

## 8. Share the view

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless \
  --host 0.0.0.0 \
  --port 8000
```

Report the live URL, selected view, projected cells and values, runtime check,
and browser evidence.
