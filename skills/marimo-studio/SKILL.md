---
name: marimo-studio
description: >-
  Build, run, and verify custom server-backed views from a Marimo notebook with
  Marimo Studio. Use when an agent needs to inspect notebook cells, compose a
  dashboard or application, project kernel values, preserve Marimo controls or
  anywidgets, work beside the live notebook editor, add HTMX interactions, or
  prepare a notebook view for deployment.
---

# Marimo Studio

Keep the notebook as the source of calculations, reactive state, controls, and
widgets. Put authored HTML, CSS, and static files under
`__marimo__/studio/<notebook-stem>/<view>/`.

Use the installed `marimo-studio` executable. In the package checkout, fall
back to `uv run marimo-studio`. Elsewhere, use `uvx marimo-studio`.

## 1. Inspect the notebook

Confirm the executable and scan displayed cells:

```console
marimo-studio --version
marimo-studio inspect analysis.py --display
```

Identify native cell names, anonymous cell indexes, definitions, controls,
anywidgets, and independent reactive branches.

Write structured records to a file so a large notebook does not fill the
terminal:

```console
marimo-studio inspect analysis.py --display --format json \
  > /tmp/marimo-studio-cells.json
```

Execute the notebook when MIME types or kernel values affect the design:

```console
marimo-studio inspect analysis.py --display --runtime --format json \
  > /tmp/marimo-studio-runtime.json
```

Runtime inspection performs the notebook's file, network, database, and data
access. Inspect `runtime.errors` before selecting a value for projection. Add
`--include-code` after narrowing the inventory when cell source is required.
Studio resolves the notebook's PEP 723 metadata together with its surrounding
project when present. When a runtime probe fails, confirm the same notebook and
branch in plain Marimo before changing a view. Repair incompatible Python or
dependency constraints in the resolved notebook environment.

## 2. Create or select a view

Create a blank dashboard:

```console
marimo-studio view add dashboard analysis.py --format json
```

For `analysis.py`, use the returned root:

```text
__marimo__/studio/analysis/dashboard/
  index.html
  app.css
```

The command adds notebook-local PEP 723 configuration when needed. Preserve
notebook code outside that metadata block and keep existing view files intact.

List and add views:

```console
marimo-studio view list analysis.py --format json
marimo-studio view add executive analysis.py --format json
```

Treat the view directory as authored source. Check its repository status:

```console
git check-ignore __marimo__/studio/analysis/dashboard/index.html
git status --short __marimo__/studio/analysis/dashboard
```

When the repository ignores `__marimo__`, add an exception scoped to
`__marimo__/studio/`.

## 3. Bind anonymous cells

Use native Marimo cell names directly. Bind each anonymous displayed cell the
view needs:

```console
marimo-studio bind filters analysis.py --cell 4
marimo-studio bind chart analysis.py --cell 9
marimo-studio bind table analysis.py --cell 12
```

Bindings belong to the notebook and are shared by every view.

After a cell's Python structure or content changes, inspect the graph and
replace its binding explicitly:

```console
marimo-studio bind chart analysis.py --cell 10 --overwrite
```

Prefer existing outputs and JSON-compatible variables. Ask the developer
before adding presentation-specific cells to the notebook.

## 4. Compose the document

Write one complete `index.html` with a single `#app-shell`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Executive summary</title>
    <link
      rel="stylesheet"
      href="./_marimo-studio/views/executive/static/app.css"
    >
  </head>
  <body>
    <main id="app-shell">
      <section aria-labelledby="chart-title">
        <h1 id="chart-title">Performance</h1>
        <marimo-cell class="chart-cell" name="chart"></marimo-cell>
      </section>
    </main>
  </body>
</html>
```

Place every cell and value host inside `#app-shell`. Mount each cell name once
per view. `<marimo-cell>` uses Marimo's output plugins and model clients, so
controls, tables, plots, downloads, and anywidgets stay attached to Python.

Link configured sibling views with their relative view URLs:

```html
<nav aria-label="Audience">
  <a href="./novice/">Novice</a>
  <a href="./intermediate/">Intermediate</a>
  <a href="./expert/">Expert</a>
</nav>
```

Studio routes these links through its view switch so the preview keeps its
kernel session and widget models.

Keep scripts that wire shell elements inside `#app-shell`. A saved HTML change
replaces that element while the Marimo runtime stays mounted. Initialize direct
listeners idempotently, or delegate events from `document`. Use the
`marimo-studio:idle` document event when setup must wait for projected outputs.

Follow the product's design system. When none exists, use
[Marimo's design guide](https://github.com/marimo-team/marimo/blob/main/DESIGN.md)
as the visual baseline.

## 5. Project kernel values

Use `mo-value` for a JSON-compatible leaf in semantic HTML:

```html
<time mo-value="report.updated_at"></time>
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

Use a root variable followed by dot selection, non-negative item indexes, or
JSON string item keys. Dot selection reads a mapping key first, then a Python
attribute.

Keep formatting, arithmetic, calls, comprehensions, and slicing in notebook
cells. Prefer several small context cells when their reactive branches update
independently.

## 6. Add HTMX behavior

Use view-scoped relative routes:

```html
<button
  type="button"
  hx-get="./_marimo-studio/views/executive/cells/table"
  hx-target="#table-region"
  hx-swap="innerHTML"
>
  Show table
</button>
<section id="table-region"></section>
```

The response contains a `<marimo-cell>` host that attaches to the current
browser store and kernel.

Serve view-owned files through the same scope:

```html
<img
  src="./_marimo-studio/views/executive/static/logo.svg"
  alt="Company"
>
```

## 7. Reserve loading space and theme outputs

Set realistic skeleton dimensions for substantial outputs:

```css
marimo-cell[name="chart"] {
  --marimo-cell-skeleton-height: 30rem;
  --marimo-cell-skeleton-color: rgb(20 24 32 / 9%);
  --marimo-cell-skeleton-radius: 0.35rem;
}

time[mo-value] {
  --marimo-value-skeleton-width: 12ch;
}
```

The runtime also caches measured cell heights by view path and viewport class.
Verify first load in a fresh browser session.

Align mounted output with the page:

```css
:root {
  color-scheme: light;
}

.chart-cell {
  --marimo-cell-background: transparent;
  --marimo-cell-foreground: #202124;
  --marimo-cell-surface: #fff;
  --marimo-cell-border-color: #d8d7d2;
  --marimo-cell-accent: #315f82;
  --marimo-cell-padding: 0;
}
```

## 8. Work beside the editor

Launch the editor and selected view:

```console
marimo-studio analysis.py --view executive
```

For browser automation:

```console
marimo-studio analysis.py \
  --view executive \
  --headless \
  --port 8000 \
  -- \
  --no-token
```

Open the printed Studio URL with a unique browser session. HTML and CSS changes
refresh in the preview. View switching keeps the preview runtime, connection,
kernel state, and widget models mounted.

Select the Preview layout before capturing the custom view. Use absolute paths
for browser screenshots and other evidence files.

Pass `--host`, `--port`, `--base-url`, and `--headless` before `--`. Trailing
arguments go to `marimo edit`. The direct launcher prepares the notebook
environment, so remove `--sandbox` and `--no-sandbox` from trailing arguments.
Use a native `marimo edit` command when a proxy URL is required.

The Studio preview iframe has `[data-preview-frame]`. Read its readiness:

```js
const frame = document.querySelector("[data-preview-frame]");
await frame.contentWindow.marimoStudio.ready();
frame.contentDocument.documentElement.dataset.marimoStudioState;
```

Record `frame.contentWindow.__MARIMO_STUDIO_SESSION_ID__` before view or shell
changes and compare it after the preview settles.

## 9. Validate in the runtime

Run the selected view through static and runtime checks:

```console
marimo-studio check analysis.py --view executive --runtime
```

Use structured streams for automation:

```console
marimo-studio check analysis.py \
  --view executive \
  --runtime \
  --format json \
  --diagnostics jsonl
```

## 10. Exercise the view in a browser

In a real browser:

1. Wait for `window.marimoStudio.ready()` in the preview.
2. Require `data-marimo-studio-state="ready"`.
3. Exercise authored controls once before the first source edit.
4. Exercise projected controls, anywidgets, HTMX fragments, and every view.
5. Confirm each `mo-value` follows its kernel value.
6. Edit HTML and CSS, then confirm authored controls still work and the preview
   session ID stays unchanged.
7. Temporarily break the template and confirm the last valid shell remains.
8. Fix the template and confirm the Studio diagnostic clears.
9. Check skeleton space, desktop and mobile layout, console errors, and failed
   requests.
10. Capture evidence to absolute paths and close the browser session.

## 11. Deploy through Marimo

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
