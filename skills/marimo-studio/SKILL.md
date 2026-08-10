---
name: marimo-studio
description: >-
  Turn Marimo notebooks into custom web pages for dashboards, reports, and
  focused tools. Use when an agent needs to inspect a notebook, create or edit
  named HTML and CSS pages, show live cell outputs or Python values, add
  browser behavior, maintain several pages backed by one notebook, validate
  them, serve them through Marimo, or export a page that runs in WebAssembly.
---

# Build custom pages from Marimo notebooks

Marimo Studio lets one notebook power dashboards, reports, and focused tools.
Keep calculations, data access, controls, plots, tables, downloads, and
anywidgets in notebook cells. Choose what an audience sees and arrange it with
HTML, CSS, and optional JavaScript. Marimo keeps the page connected to the
running notebook, so controls and dependent outputs continue to update.

A **custom view** is one named web page backed by a notebook. Studio uses the
word `view` in its commands. Each custom view has its own `index.html` and
`app.css`. Several views can share the notebook's Python code and interactive
state.

## Terms

| Term               | Meaning                                                                               |
| ------------------ | ------------------------------------------------------------------------------------- |
| Notebook           | The Marimo `.py` file that owns Python code, data, controls, and displayed outputs    |
| Custom view        | A named HTML and CSS page that shows selected notebook content                        |
| Cell name          | A native Marimo cell name or a saved Studio name for an unnamed cell                  |
| Value reference    | A Python variable selector used by `mo-value` or `<marimo-output>`                    |
| Server preview     | A custom view connected to the active Python kernel while developing or serving       |
| WebAssembly export | A static directory where the notebook runs in the browser                             |
| Static check       | Validation that reads and compiles saved files without executing notebook code        |
| Runtime check      | Validation that executes the notebook and checks the actual outputs and Python values |

## Workflow

1. Inspect the notebook and existing custom views.
2. Create or select one named view.
3. Decide which complete cells, rich objects, and Python values the audience needs.
4. Edit the view's `index.html`, `app.css`, and optional relative files.
5. Develop beside the running notebook in `marimo edit`.
6. Run the static check, then the runtime check.
7. Serve the notebook through `marimo run` or export one view for WebAssembly.

## Keep Python work in the notebook

- Keep notebook cell bodies unchanged unless the user requests notebook work.
- Read existing view files completely before editing them. The browser,
  another agent, or an external editor may have changed them.
- Use an existing Marimo cell name when it clearly identifies the output.
- Use `marimo-studio bind` when an unnamed cell needs a memorable name in HTML.
- Keep the Server preview selected during development. It uses the notebook's
  active Python kernel.
- Test the WebAssembly option when the user requests a static export. It runs
  the notebook in the browser.

`marimo-studio view add` may add the `marimo-studio` dependency and
`[tool.marimo-studio]` settings to the notebook's inline dependency header.
It also creates the view files. It leaves notebook cell bodies unchanged.

## 1. Inspect the notebook

List its custom views and cells that display an output:

```console
marimo-studio view list analysis.py --format json
marimo-studio inspect analysis.py --display --format json
```

The JSON output identifies:

- the default view and every available view
- each cell's native name, if it has one
- each cell's zero-based position
- the lines containing the cell
- variables the cell defines and reads
- cells that end with a displayed result

Add `--include-code` when the short preview and variable names do not explain a
cell. Add `--limit` for the first pass through a large notebook.

Static inspection reads and compiles the saved notebook. It does not execute
cells. Inspect actual cell outputs, rich outputs, and JSON-compatible Python
values when the saved source leaves a content decision unresolved:

```console
marimo-studio inspect analysis.py \
  --display \
  --runtime \
  --format json \
  --diagnostics jsonl
```

`--runtime` executes the notebook. Its code may read files, make network or
database requests, and perform other configured side effects. The result adds
the actual output formats and readable Python values. `--diagnostics jsonl`
writes machine-readable progress and errors to standard error.

## 2. Create a custom view

Create the default `dashboard` page for one audience or task:

```console
marimo-studio view add analysis.py --format json
```

View names start with a lowercase letter and contain lowercase letters,
numbers, or hyphens. A new view starts with every notebook cell in source order,
so it has working content before customization. Studio gives each unnamed cell
a saved name that remains usable when nearby cells move or change.

For `analysis.py`, the command creates:

```text
__marimo__/studio/analysis/dashboard/
  index.html
  app.css
```

Add relative files such as `app.js`, images, fonts, or data beneath the same
view directory. Reference them with relative URLs from `index.html`.

Create more pages from the same notebook when audiences need different
wording, content, or tasks:

```console
marimo-studio view add analysis.py --name report --format json
marimo-studio view add analysis.py --name operations --format json
```

## 3. Choose what the page shows

Decide before editing:

1. Who will use the page?
2. What question or action should its first screen support?
3. Which notebook outputs answer that question?
4. Which details belong farther down the page?

Use the element that matches the content:

| Notebook content                                            | HTML                                        |
| ----------------------------------------------------------- | ------------------------------------------- |
| Complete cell output, including logs and errors             | `<marimo-cell name="...">`                  |
| One rich object as a native table, plot, control, or widget | `<marimo-output value="variable.path">`     |
| String, number, list, dictionary, or nested field           | Any element with `mo-value="variable.path"` |

Show the complete output from a named cell:

```html
<marimo-cell name="revenue_chart"></marimo-cell>
```

If the cell is unnamed, give it a stable name using the zero-based position
reported by `inspect`:

```console
marimo-studio bind analysis.py \
  --cell 4 \
  --as revenue-chart \
  --format json
```

Studio calls this saved name an alias. Reinspect the notebook before using
`--overwrite` when an existing alias points to a cell that has changed or can
no longer be identified uniquely. A cell output may appear once in each view.

Show one Python object through Marimo's native output formatter:

```html
<marimo-output value="df"></marimo-output>
<marimo-output value="report.figure"></marimo-output>
<marimo-output value="results[0]"></marimo-output>
```

Use this form for a DataFrame, plot, Markdown object, control, or widget whose
native output belongs at that point in the page. Keep one host for each
rich-output selector.

Show a JSON-compatible Python value as text:

```html
<time mo-value="report.updated_at"></time>
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

The `value` on `<marimo-output>` and the text inside `mo-value` use the same
value-reference grammar. A reference starts with a notebook variable and can
select attributes, dictionary keys, and list items. Put formatting, arithmetic,
slicing, function calls, and comprehensions in a notebook cell when notebook
changes are part of the task.

## 4. Write the page

Write one complete HTML document with one `<main id="app-shell">`. Put every
`<marimo-cell>`, `<marimo-output>`, and `mo-value` host inside that main
element:

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

Studio provides classes for responsive grids, spacing, typography, colors, and
borders. The stable shortcuts `studio-view`, `studio-card`, `studio-button`,
and `studio-eyebrow` use the colors and dimensions defined in `app.css`.

Keep headings in order, label controls, preserve visible keyboard focus, and
let wide tables and plots shrink or scroll inside their section.

## 5. Add browser behavior

Use ordinary browser APIs and ECMAScript modules. A hidden `mo-value` element
can pass structured Python data to JavaScript:

```html
<span id="report-data" hidden mo-value="report"></span>
<output id="report-total"></output>
<script type="module" src="app.js"></script>
```

Listen for changes before reading the current value in `app.js`:

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

`source.marimoValue` is the current JSON-compatible Python value. `undefined`
means the value has not arrived or the reference cannot currently be read.
JSON `null` remains a valid value. The last received value remains available
while an updated value is loading.

Listen for `marimo-value-error` when the page needs a local error message. Use
`window.marimoStudio.ready()` when browser code must wait for the current
projections to finish loading or report an error.

## 6. Style loading and notebook output

Keep the shared light and dark color variables under `/* THEME */` at the top
of `app.css`. Put page-specific rules under `/* APP */`. Preserve the starter
`--marimo-cell-*` mappings so notebook output inherits the page's fonts,
surfaces, and accent color.

Reserve realistic space for large cells, rich outputs, and values while they
load:

```css
marimo-cell.trend {
  --marimo-cell-skeleton-height: 28rem;
}

marimo-output[value="df"] {
  --marimo-cell-skeleton-height: 24rem;
}

time[mo-value] {
  --marimo-value-skeleton-width: 12ch;
}
```

Use the `--marimo-cell-*` variables to change cell padding, border, radius,
background, fonts, and accent color. Prefer the surrounding page section as
the visible container, with the notebook output integrated into that surface.

## 7. Develop beside the notebook

Open the configured notebook in Marimo:

```console
marimo edit analysis.py --sandbox
```

Open a notebook directory when one Marimo gallery should cover several files:

```console
marimo edit notebooks/ --sandbox
```

The gallery stays at the root. Opening a configured notebook enters Studio,
while other notebooks open in Marimo's native editor.

The **Build** screen shows the notebook and custom page together. Open
**HTML & CSS** to edit `index.html` and `app.css` in the browser. Changes saved
there or in an external editor stay synchronized with the same files on disk.

Use the Server preview while developing. It connects the custom page to the
editor's Python kernel. Saving CSS updates the current styles. Saving HTML
replaces the custom page structure while the kernel keeps running. Changing a
referenced JavaScript module reloads the custom page so the browser imports the
new module.

After each change, confirm that controls, tables, plots, downloads, and
anywidgets still respond and that notebook edits update dependent content.

## 8. Validate and repair

Run the static check after editing the notebook or view files:

```console
marimo-studio check analysis.py \
  --view dashboard \
  --format json \
  --diagnostics jsonl
```

The static check reads and compiles the saved notebook and view files. It
checks cell names, value references, HTML structure, view configuration, and
packaged browser files. It does not execute notebook code.

Run the runtime check before sharing or exporting:

```console
marimo-studio check analysis.py \
  --view dashboard \
  --runtime \
  --format json \
  --diagnostics jsonl
```

The runtime check executes the notebook and verifies the actual cell outputs
and Python values used by the selected view. Each diagnostic includes the view,
the failing reference, its source location, and a repair hint.

| Problem                               | Repair                                                    |
| ------------------------------------- | --------------------------------------------------------- |
| Cell name is missing                  | Use a current native name or bind the intended cell       |
| Saved cell name is stale or ambiguous | Reinspect, then bind the intended cell with `--overwrite` |
| Python value reference is unknown     | Correct its root variable or nested path                  |
| Python value fails during execution   | Inspect the cell that defines it and its current output   |
| The notebook has no custom view files | Create the configured default view                        |

Use the diagnostics as a repair queue. Fix one cause, rerun the same command,
and continue until no result has `status: "fail"`.

Inspect the running page after both commands pass:

- The first screen supports the named audience and task.
- Every referenced cell and Python value finishes loading.
- Controls, tables, plots, downloads, and anywidgets remain interactive.
- Notebook edits update the dependent page content.
- HTML, CSS, and JavaScript edits refresh from disk.
- Loading placeholders reserve enough space to prevent disruptive layout
  shifts.
- The page remains readable at narrow and wide widths.
- Light and dark appearance preserve readable contrast.
- Keyboard focus and control labels remain visible.

## 9. Serve or export

Serve every configured custom view through Marimo:

```console
marimo run analysis.py --sandbox --headless
```

The default view is available at `/`. A view named `report` is available at
`/report/`. Each browser receives its own Python kernel session.

Export one custom view when the notebook can run in WebAssembly:

```console
marimo-studio export analysis.py \
  --view report \
  --output dist/report \
  --format json \
  --diagnostics jsonl
```

Run the runtime check before export. Use `--force` after reviewing an existing
output directory that should be replaced. Edit the notebook or view source for
later changes, then export again.

## Handoff

Report:

- the notebook path and custom view names
- the audience and primary task for each changed view
- the HTML, CSS, JavaScript, and relative asset files changed
- the cell names and Python value references used by each view
- any inline notebook configuration or saved cell names added
- the static and runtime check results
- the interactions, loading states, widths, and color modes inspected

Leave the notebook and every changed custom view runnable with no failing
checks.
