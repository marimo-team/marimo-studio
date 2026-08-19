# View authoring

A Studio view is one complete web document backed by a Marimo notebook. Each
named view owns its HTML, CSS, browser modules, images, fonts, and other relative
assets. The notebook owns Python computation and reactive objects.

## Inspect and select notebook content

Use `overview` to read configuration and view state before mutation. Use
`inspect` to identify native cell names, zero-based positions, source lines,
definitions, references, and displayed expressions.

```console
marimo-studio overview analysis.py --format json
marimo-studio inspect analysis.py --display --format json
```

Add `--include-code` when names and previews do not explain a cell. Add
`--limit N` to bound the first inspection. Runtime inspection executes notebook
code and can perform its configured file, network, database, and data access:

```console
marimo-studio inspect analysis.py \
  --display \
  --runtime \
  --runtime-timeout 120 \
  --format json \
  --diagnostics jsonl
```

## Create a view

Create the default `dashboard` view or name another audience-specific page:

```console
marimo-studio view add analysis.py --format json
marimo-studio view add analysis.py --name report --format json
```

A new view starts with every notebook cell in source order. Studio writes the
view beneath the notebook-local source tree:

```text
__marimo__/studio/analysis/dashboard/
  index.html
  app.css
```

Add `app.js`, images, fonts, or data beneath the same directory and reference
them with relative URLs.

## Choose a projection

Use the projection that matches the content:

| Notebook content                                  | HTML                                        |
| ------------------------------------------------- | ------------------------------------------- |
| Complete cell output, including logs and errors   | `<marimo-cell name="...">`                  |
| One rich object rendered by Marimo                | `<marimo-output value="variable.path">`     |
| String, number, list, dictionary, or nested field | Any element with `mo-value="variable.path"` |

Show a complete named cell:

```html
<marimo-cell name="revenue_chart"></marimo-cell>
```

Bind an unnamed cell using the zero-based position returned by inspection:

```console
marimo-studio bind analysis.py \
  --cell 4 \
  --as revenue-chart \
  --format json
```

Reinspect before using `--overwrite`. A saved alias follows the intended cell
through routine source movement and formatting changes.

Show one rich Python object through Marimo's native output formatter:

```html
<marimo-output value="df"></marimo-output>
<marimo-output value="report.figure"></marimo-output>
<marimo-output value="results[0]"></marimo-output>
```

Show a JSON-compatible value as text:

```html
<time mo-value="report.updated_at"></time>
<strong mo-value="selection.count"></strong>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

`<marimo-output value>` and `mo-value` share one selector grammar. A selector
starts with a notebook variable and can read attributes, dictionary keys, and
list items. Put arithmetic, formatting, slicing, function calls, and
comprehensions in notebook cells.

Studio resolves every cell, output, and value host to its current producing cell
after the runtime connects. Integrations such as Marimo Lens consume that
derived identity. Keep view source anchored to `name`, `value`, and `mo-value`
references so the page remains readable and editable.

`marimo_studio.LENS_TARGET_SELECTOR` owns the projection-host CSS policy used
when mounting Lens. Compose authored page regions into that selector in the
notebook. Import the public constant so Studio remains the owner of host
selector policy.

## Write the document

Write one complete HTML document with one `<main id="app-shell">`. Put every
projection host inside that element:

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
      <section class="studio-card p-5" aria-labelledby="trend-title">
        <h1 id="trend-title" class="text-2xl font-semibold">Revenue trend</h1>
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

Use Wind4 utility classes in `index.html` for regular grids, spacing,
typography, color, borders, and state variants. The vocabulary follows UnoCSS
Wind4 and Tailwind 4 syntax. Keep theme tokens, custom keyframes, and CSS rules
that need the cascade in `app.css`.

Keep headings in order, label controls, preserve visible keyboard focus, and
let wide plots and tables shrink or scroll inside their sections.

## Add browser behavior

Use standard browser APIs and ECMAScript modules. A hidden `mo-value` host can
pass structured Python data to a module:

```html
<span id="report-data" hidden mo-value="report"></span>
<output id="report-total"></output>
<script type="module" src="app.js"></script>
```

Listen for updates before reading the current value:

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

`source.marimoValue` contains the current JSON-compatible Python value.
`undefined` means the value has not arrived or cannot currently be read. JSON
`null` remains a valid value. Listen for `marimo-value-error` when the page needs
a local error state. Use `window.marimoStudio.ready()` when browser code must
wait for current projections to settle.

## Style loading and notebook output

Keep shared light and dark variables under `/* THEME */` at the top of
`app.css`. Put page-specific rules under `/* APP */`. Preserve the starter
`--marimo-cell-*` mappings so notebook output inherits the page typography,
surfaces, and accent color.

Reserve realistic space while large projections load:

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

Use the surrounding section as the visible container and integrate notebook
output into that surface.
