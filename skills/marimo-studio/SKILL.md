---
name: marimo-studio
description: >-
  Design and maintain audience-specific Marimo Studio views for existing
  Marimo notebooks. Use when an agent needs to inspect notebook outputs,
  create a view, edit its HTML, theme, and CSS, arrange live cells and Python
  values, apply a clean visual system, or verify the result in a browser.
---

# Design Marimo Studio views

Treat the notebook as the source of computation, reactive state, controls,
plots, tables, downloads, and anywidgets. A Studio view arranges selected
notebook outputs into an audience-specific page with HTML and CSS.

View source lives beside the notebook:

```text
__marimo__/studio/<notebook-stem>/<view>/
  index.html
  theme.css
  app.css
```

Keep notebook cells byte-identical unless the user asks for notebook changes.
Work in the view files and use Studio bindings when an anonymous cell needs a
stable presentation name. Creating a view may add Studio configuration to the
notebook's PEP 723 metadata.

## Start with the design direction

Read design guidance before editing the view. Follow user-provided brand
rules, screenshots, or reference products when present.

When the user supplies no aesthetic direction, read Marimo's current design
mandates first:

```console
curl -fsSL https://raw.githubusercontent.com/marimo-team/marimo/refs/heads/main/DESIGN.md
```

Use that document as the default visual system. Aim for a compact,
software-native page with semantic surfaces, slate borders, muted secondary
text, restrained blue interaction color, an 8px spacing rhythm, and small
radii. Use borders before shadows. Keep tables, charts, and notebook outputs
full-width and overflow-safe. Reserve cards for repeated items or genuinely
framed tools. Skip decorative gradients, nested cards, marketing-style hero
sections, one-off palettes, and decorative animation.

The packaged font stack follows Marimo and falls back to native system fonts.
Set `--text-font`, `--heading-font`, or `--monospace-font` in `theme.css` when
the supplied design system chooses another typeface. Add the corresponding
font resource to `index.html` when the face is not already available.

## Discover the available material

Resolve the notebook path and inspect its configured views and displayed
cells before choosing page content:

```console
marimo-studio view list analysis.py --format json
marimo-studio inspect analysis.py --display --format json
```

If `view list` reports that a configured view directory is missing, recreate
that view with `marimo-studio view add <view> analysis.py --format json` before
continuing. This can happen when a notebook file was copied without its
`__marimo__` directory.

Use `uvx marimo-studio` when the command is not installed. Add
`--include-code` when cell previews and definitions do not reveal enough to
choose the right output.

Read `index.html` and `app.css` completely when the target view exists. Read
`theme.css` when present. Preserve its working projections, source paths,
interaction model, and visual language unless the user asks for a redesign.
Create `theme.css` when the view needs shared semantic tokens.

Use runtime inspection when output MIME types or JSON-compatible values affect
the design:

```console
marimo-studio inspect analysis.py --display --runtime --format json
```

Runtime inspection executes notebook code, including its file, network,
database, and data access.

## Create a view

Create a named view through the CLI:

```console
marimo-studio view add dashboard analysis.py --format json
```

The generated view includes every notebook cell in source order and creates
stable aliases for anonymous cells. Use it as a runnable inventory, then keep
the outputs that serve the target audience and arrange them around that
audience's task.

Use lowercase letters, numbers, and hyphens in view names. Run `view list`
again to confirm the source paths before editing.

## Compose the page

Write one complete HTML document with one `#app-shell`. Keep every cell and
value projection inside that shell:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Quarterly performance</title>
    <link rel="stylesheet" href="./_marimo-studio/views/dashboard/static/app.css" />
  </head>
  <body>
    <main id="app-shell" class="studio-view grid gap-6 lg:grid-cols-2">
      <header class="lg:col-span-2">
        <p class="studio-eyebrow">Quarterly review</p>
        <h1 class="text-4xl font-semibold tracking-tight">Performance at a glance</h1>
      </header>
      <section class="studio-card p-5" aria-labelledby="trend-title">
        <h2 id="trend-title" class="flex items-center gap-2 text-lg font-semibold">
          <iconify-icon icon="lucide:chart-no-axes-combined" aria-hidden="true"></iconify-icon>
          Trend
        </h2>
        <marimo-cell class="chart" name="revenue-chart"></marimo-cell>
      </section>
    </main>
  </body>
</html>
```

Choose the projection primitive by content:

| Need                                                            | Primitive                  |
| --------------------------------------------------------------- | -------------------------- |
| A control, plot, table, download, markdown output, or anywidget | `<marimo-cell name="...">` |
| A JSON-compatible label, number, date, or nested field          | `mo-value`                 |
| Detail loaded after a user action                               | An HTMX cell route         |

Use a native cell name reported by `inspect`, or bind an anonymous cell:

```console
marimo-studio bind revenue-chart analysis.py --cell 4
```

Render each cell name once per view. `<marimo-cell>` keeps the output connected
to Marimo's output plugins and widget clients.

`<marimo-cell>` renders a cell's displayed result. For a definition-only cell,
project its JSON-compatible Python value with `mo-value`.

Load a secondary cell after a user action with its view-scoped HTMX route:

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

The response mounts `detail_table` through the current Marimo session.

## Use the built-in styling vocabulary

Write Wind4 utilities directly in `index.html`. Studio scans the initial shell,
HTML refreshes, and later HTMX fragments. Use responsive and state variants in
the same class attribute:

```html
<section class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
  <article class="studio-card p-5 hover:border-primary">
    <p class="studio-eyebrow">Revenue</p>
    <strong class="text-3xl font-semibold" mo-value="summary.revenue"></strong>
  </article>
</section>
```

The stable shortcuts are `studio-view`, `studio-card`, `studio-button`, and
`studio-eyebrow`. Use ordinary utilities for the rest of the layout.

Set semantic variables in `theme.css`. Use `light-dark()` with
`color-scheme: light dark` when the view should follow the browser theme:

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

Semantic utilities such as `bg-card`, `text-foreground`, `border-border`, and
`text-primary` read these tokens. Preserve the starter theme's `marimo-cell`
mapping so projected outputs receive the palette. Put view-specific component
selectors in `app.css`, which loads after utilities and `theme.css`.

Use `<iconify-icon>` with the same icon names accepted by `mo.icon()`:

```html
<iconify-icon icon="lucide:leaf" aria-hidden="true"></iconify-icon>
```

Icon data loads lazily from Iconify. Use `aria-hidden="true"` for decorative
icons. Use `role="img"` and an `aria-label` when an icon carries meaning.

Read existing Python values with selectors:

```html
<strong mo-value="summary.total"></strong>
<time mo-value="report.updated_at"></time>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

Selectors support attribute access and item lookup. Put formatting,
arithmetic, calls, comprehensions, and slicing in a notebook cell when
notebook changes are in scope.

## Edit with the live preview

Edit `index.html`, `theme.css`, and `app.css` in an external editor or in
Studio's source panes. Saved source refreshes the visible shell while the
Marimo runtime, kernel session, controls, and widget models stay mounted.

Keep behavior in notebook cells and HTMX requests. Avoid copying reactive
state into page JavaScript. When direct event listeners are necessary,
delegate from `document` or make initialization safe to repeat after a shell
refresh.

Studio's toolbar can run the preview through the Server or WebAssembly
runtime. Studio prepares WebAssembly in a background frame while Server is
active. Change a native control, switch to WebAssembly, wait for `ready` when
warmup is still in progress, and confirm the control and its dependent outputs
retain the value. Repeat the check in the other direction.

Runtime state sharing belongs to the Studio workspace. A direct WebAssembly
view opened in a separate browser session has its own kernel and control
state.

## Integrate notebook output into the layout

Build a clear reading order before styling individual regions. Use semantic
landmarks and headings, then compose responsive grid or flex layouts with
utilities. Keep normal page sections visually open. Frame repeated records,
filters, or tools when the boundary helps the reader act. Reserve `app.css`
for named components and selectors that are clearer as ordinary CSS.

Let mounted outputs inherit the page typography and colors. Remove incidental
cell framing when the surrounding section already provides structure:

```css
marimo-cell {
  display: block;
  min-width: 0;
  --marimo-cell-font: var(--text-font);
  --marimo-cell-border: 0;
  --marimo-cell-radius: 0;
  --marimo-cell-padding: 0;
}
```

Reserve first-load space for substantial outputs so the page stays stable:

```css
marimo-cell.chart {
  --marimo-cell-skeleton-height: 28rem;
}

time[mo-value] {
  --marimo-value-skeleton-width: 12ch;
}
```

Use realistic skeleton heights for charts, tables, galleries, and anywidgets.
Check the first load in a fresh browser session.

## Validate through the user boundary

Run the view check after each coherent edit:

```console
marimo-studio check analysis.py \
  --view dashboard \
  --runtime \
  --format json \
  --diagnostics jsonl
```

Repair each reported source location, missing cell, stale binding, or value
selector before browser acceptance.

Open the notebook through Marimo on an unused local port:

```console
uv run --with marimo-studio \
  marimo edit analysis.py \
  --sandbox \
  --headless \
  --no-token \
  --port 8000
```

When validating an editable Marimo Studio checkout, use `--no-sandbox` so
Marimo loads that checkout's Python package and browser assets. Use
`--sandbox` for the notebook's declared environment.

Launch the server through the execution tool's managed long-running process
support. Poll the server until it responds before opening a browser.

In edit mode, open the Studio workspace first. It mounts the native editor and
creates the notebook session that its preview and the direct view share:

```text
http://127.0.0.1:8000/studio/dashboard/
```

Wait for the workspace preview to render, then open the direct custom view for
visual and interaction acceptance:

```text
http://127.0.0.1:8000/dashboard/
```

`agent-browser wait --text` reads the top-level document. For workspace
acceptance, inspect the visible preview iframe in the accessibility snapshot or
query `iframe[data-preview-runtime-frame]:not([hidden])` through
`contentDocument`. Use the direct view for ordinary text waits and detailed
content checks.

The direct edit-mode view attaches to the editor kernel and cannot create that
session by itself. Use `marimo run` when testing a standalone view that should
create an isolated run session. In run mode, the default view is also available
at `/`.

Use separate `$agent-browser` sessions for the workspace and direct view so
editor logs do not contaminate direct-view acceptance. Wait for the direct
document to report readiness before inspecting its content:

```console
agent-browser --session <id> wait --fn \
  'document.documentElement.dataset.marimoStudioState === "ready"'
```

Verify the direct view at desktop and mobile widths, then check:

1. The page hierarchy matches the named audience and task.
2. Every projected cell and value reaches a ready state.
3. Controls, tables, plots, downloads, and anywidgets remain interactive.
4. A reversible HTML and CSS edit appears without navigation and preserves
   current control state.
5. Skeletons reserve enough space on a fresh load.
6. Content remains readable without horizontal page overflow.
7. Keyboard focus is visible and labels remain associated with controls.
8. The console and network log contain no unexpected failures.

Fix accessibility and browser failures owned by the view's HTML and CSS.
Report failures inside Marimo-rendered controls or anywidgets separately.
Change notebook cells or runtime code only when the user includes them in
scope.

## Export for static hosting

Export a selected view after its WebAssembly preview passes browser acceptance:

```console
marimo-studio export analysis.py \
  --view dashboard \
  --output dist/dashboard
python -m http.server --directory dist/dashboard
```

Wait for `data-marimo-studio-state="ready"` at the HTTP URL, then repeat the
control, projection, anywidget, responsive layout, console, and network checks.
Verify HTMX interactions that load built-in cell fragments. Pass `--force`
when replacing a previously reviewed output directory.

The exported directory contains the notebook source and runs it in Pyodide.
Confirm that PEP 723 dependencies install in the browser and that the notebook
contains no credentials or private source before handoff. Deploy the complete
directory. Treat it as generated output and make revisions in the notebook or
view source.

Close the browser session and stop the local server after collecting evidence.

Report the view name, edited files, projected cells and values, check result,
and browser evidence. Mention notebook edits only when the user requested and
approved them.
