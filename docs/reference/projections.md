---
title: Notebook result projections
description: Exact cell, output, value, selector, event, state, duplication, and data contracts for rendered views.
---

# Notebook result projections

A projection host places one notebook result in a view. Studio resolves the
host to one producer cell, runs its dependency closure in the selected notebook
runtime, and mounts the result in the host element.

| Host                            | Target                          | Browser result                                           |
| ------------------------------- | ------------------------------- | -------------------------------------------------------- |
| `<marimo-cell name="summary">`  | Named cell or Studio cell alias | Complete native cell presentation                        |
| `<marimo-output value="chart">` | Notebook value selector         | One value rendered by marimo's output renderer           |
| `mo-value="metrics.total"`      | Notebook value selector         | JSON value or Arrow-backed table exposed to browser code |

Pages use the hosts above, which Quarto's `marimo` shortcode also writes. A
render reads the same cells, outputs, and values on the server: Typst reads
targets with `marimo_value()`, `marimo_output()`, and `marimo_cell()`, and
LaTeX with `\marimovalue`, `\marimographics`, and `\marimocell`. A page shows
a render's files with `<marimo-output render="...">`, as
[Rendered files](#rendered-files) describes.

The Python (`server`) and Browser (`wasm`) runtimes use the same authored
hosts.
In HTML, close each host explicitly and place hosts beside each other.
Rendering a host replaces its contents. The build rejects nested hosts and
self-closing elements such as `<h1 mo-value="total"/>`.

```html
<h1 mo-value="total"></h1>
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
```

## Complete cells

```html
<marimo-cell name="summary"></marimo-cell>
```

`name` accepts a native marimo cell name or an alias under
`[tool.marimo-studio.cells]`. The host receives the cell's native output,
controls, console output when `show_cell_logs` is enabled, error state, and
reactive updates.

A presentation mounts each cell target once. A second host for the same target
enters `data-state="error"` with code `duplicate-cell-host`.

## Rendered outputs

```html
<marimo-output value="chart"></marimo-output>
```

`value` selects a Python value, so assign the figure or object to a notebook
variable, such as `chart = plot_revenue(rows)`. marimo renders it through its
native output renderer and updates it when its producer reruns.

`accept` shows the value as an image instead. List image types in order of
preference, separated by spaces or commas:

```html
<marimo-output value="chart" accept="image/svg+xml image/png"></marimo-output>
```

Studio renders the value in the first listed type it supports through
marimo-export's
[`represent()`](https://marimo-team.github.io/marimo-export/reference/python/values).
The notebook's output settings stay unchanged, so the notebook can show a PNG
while the page shows an SVG.

- A page host accepts `image/svg+xml`, `image/png`, `image/jpeg`, and
  `image/gif`.
- A matplotlib figure or axes renders as SVG or PNG. A PNG displays at the size
  marimo shows the figure with twice the pixels, for high-density screens.
- An Altair chart renders as SVG or PNG with `vl-convert-python`. The Browser
  runtime lacks `vl-convert-python`, so leave `accept` off there to show the
  interactive chart. Select the chart itself, not a `mo.ui.altair_chart`
  wrapper.
- Other values use their display methods.
- A figure keeps the style it was drawn with, including marimo's dark-theme
  style.

A value without an accepted type puts the host in `data-state="error"` with
code `output-media-unavailable`. Studio reads `accept` at build time, so later
script changes to the attribute have no effect.

A view reads each output target in one form. Every literal host and every
document that reads a target lists the same media types, and a different list
reports `output-accept-conflict` at its source location. A host with
`data-marimo-allow="*"` shows each target in the form its literal hosts
declare, and an `accept` on that host reports `projection-accept-invalid`.

A presentation mounts each output target once. A second host for the same
target enters `data-state="error"` with code `duplicate-output-host`.

## Browser values

```html
<strong mo-value="metrics.total"></strong>
```

Studio writes a scalar value into the element's text content, `null` as an
empty string, and arrays and objects as compact JSON. The host's
non-enumerable, read-only `marimoValue` property holds the decoded value:

```js
const host = document.querySelector('[mo-value="metrics.total"]');

host.addEventListener("marimo-value-updated", (event) => {
  console.log(event.detail.value);
  console.log(host.marimoValue);
});
```

Several `mo-value` hosts may select the same target. Each receives its own
update event and reads the current decoded value.

### Value selectors

A value selector starts with a notebook variable and may contain these path
steps:

```text
metrics.total
rows[0]
lookup["north-region"]
```

| Syntax    | Resolution                                      |
| --------- | ----------------------------------------------- |
| `name`    | Notebook variable                               |
| `.field`  | Mapping key when present, then Python attribute |
| `[0]`     | Non-negative item index                         |
| `["key"]` | Item access with a JSON string key              |

The root uses Python identifier syntax. Dot selection rejects names that start
with `_`. Bracket indexes must be JavaScript safe integers. A selector has at
most 64 path steps and 4,096 UTF-8 bytes. Studio parses selectors with
marimo-export's
[`ValueSelector`](https://marimo-team.github.io/marimo-export/reference/python/values#valueselector),
so a view and a Prepared export accept the same selectors.
[Limits](limits.md) lists the complete projection budget.

### Value codecs

| Codec          | JavaScript value                                         | Contract                                                                       |
| -------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `json-v1`      | `null`, boolean, number, string, array, or object        | `marimoValue` returns the decoded JSON-compatible value                        |
| `arrow-ipc-v1` | [Flechette](https://github.com/uwdata/flechette) `Table` | `marimoValue` returns the table with its source bytes and fingerprint attached |

A `json-v1` value encodes within 1,000,000 bytes and an `arrow-ipc-v1` value
within 64 MiB. [Runtime payloads](limits.md#runtime-payloads) lists the
per-read budgets.

Studio decodes Arrow tables with Flechette's default extraction options.
Integer columns, including 64-bit integers, read as numbers, and a 64-bit value
beyond `Number.MAX_SAFE_INTEGER` throws. Booleans and strings keep their
JavaScript types, list cells read as arrays, and dates and timestamps read as
epoch milliseconds. `table.toArray()` returns plain row objects.

React starters export `useMarimoValue()` and `getMarimoDataSource()` from
`src/lib/use-marimo-value.ts`, and Svelte starters export
`observeMarimoValue()` and `getMarimoDataSource()` from
`src/lib/marimo-value.ts`. `getMarimoDataSource(table)` returns the codec,
fingerprint, and immutable
[Arrow IPC](https://arrow.apache.org/docs/format/Columnar.html#serialization-and-interprocess-communication-ipc)
bytes of an Arrow-backed table. Arrow IPC is a columnar data interchange
format.

## Host lifecycle

Studio records the current lifecycle phase in `data-state`.

| State        | Meaning                                                               | `aria-busy`                       |
| ------------ | --------------------------------------------------------------------- | --------------------------------- |
| `connecting` | The host is waiting for projection resolution or a runtime connection | `true`                            |
| `loading`    | The producer or selected result is pending                            | `true`                            |
| `stale`      | The host retains a previous result while a current result is pending  | `true` for output and value hosts |
| `ready`      | The host displays the current result                                  | Removed                           |
| `missing`    | A complete-cell target has no current result                          | Removed                           |
| `error`      | Resolution, execution, rendering, duplication, or decoding failed     | Removed                           |

Value hosts keep their previous `marimoValue` while entering `loading` or
`stale`. A terminal value error clears the property and dispatches
`marimo-value-error`.

### Cell events

| Event                 | Dispatch                                        | Detail fields                                                         |
| --------------------- | ----------------------------------------------- | --------------------------------------------------------------------- |
| `marimo-cell-ready`   | First transition to `ready`                     | `alias`, `runtimeId`, `outputMime`, or diagnostic fields when present |
| `marimo-cell-updated` | A later transition to `ready`                   | Same shape as `marimo-cell-ready`                                     |
| `marimo-cell-error`   | First transition into the current `error` state | `alias`, `runtimeId`, `code`, `message`, `hint` when present          |

### Output events

Value hosts, `<marimo-output value>`, dispatch these details. Render hosts
dispatch the same event names with a
[render record](#render-records).

| Event                   | Dispatch                                        | Detail fields                                                       |
| ----------------------- | ----------------------------------------------- | ------------------------------------------------------------------- |
| `marimo-output-ready`   | First transition to `ready`                     | `selector`, `cellId`, `mimetype`, or diagnostic fields when present |
| `marimo-output-updated` | A later transition to `ready`                   | Same shape as `marimo-output-ready`                                 |
| `marimo-output-error`   | First transition into the current `error` state | `selector`, `cellId`, `code`, `message`, `hint` when present        |

### Value events

| Event                  | Detail                               |
| ---------------------- | ------------------------------------ |
| `marimo-value-updated` | `{ selector, value }`                |
| `marimo-value-error`   | `{ selector, code, message, hint? }` |

Host events bubble and cross
[shadow DOM](https://developer.mozilla.org/en-US/docs/Web/API/Web_components/Using_shadow_DOM)
boundaries. Shadow DOM is the browser boundary that encapsulates a component's
internal document tree. Listen on the host for one projection or on `document`
for the presentation.

## Authored sites and dynamic targets

A view provider reports each authored host as a projection site. Studio adds
`data-marimo-studio-site` to the host in the build snapshot, and the attribute
carries the site into the built page. Leave that attribute to Studio.

A site with a finite target set can request those targets. A site with targets
`"*"` permits a dynamic target of the declared kind. The built-in React and
Svelte providers infer finite targets from literals and bounded constant
expressions. Add `data-marimo-allow="*"` when a framework expression selects
its target at runtime:

```tsx
<marimo-cell name={selectedName} data-marimo-allow="*" />
```

The HTML provider authorizes each host for its authored target. Add the same
wildcard when page JavaScript changes the host's selector:

```html
<span id="details" hidden mo-value="details.first" data-marimo-allow="*"></span>
```

An unbounded expression without the literal wildcard produces
`projection-target-unbounded`, and any other `data-marimo-allow` value produces
`projection-wildcard-invalid`. Static validation checks finite targets, and
browser assertions verify the rendered results of a dynamic site.

Changing `name`, `value`, or `mo-value` releases the prior target and resolves
the same DOM instance against the new one. Removing the host releases its
projection ownership.

## Rendered files

A render host shows the files a view provider renders from notebook results,
such as the PDF the Typst or LaTeX provider compiles or a video a scene
provider encodes:

```html
<marimo-output render="main.typ"></marimo-output>
```

`render` names the project file the render starts from, as Source shows its
path. A host for a file the view does not render enters `error` with code
`render-unknown`, and the build fails with the same code when the built
page's HTML holds one. A host with both `render` and
`value` enters `error` with code `render-host-invalid`. A render
host is part of the page and needs no projection site.

Studio renders again whenever a result the render reads changes. The first
change to those results during a render cancels it, and later changes wait for
the replacement to finish, so results that change faster than renders finish
still show. The host keeps the last files on screen while new ones render, and
shows render errors beside them. It shows the main file by its media type:

| Main file          | The host shows                                                   |
| ------------------ | ---------------------------------------------------------------- |
| `application/pdf`  | The pages, with selectable text                                  |
| `image/*`          | The image                                                        |
| `video/*`          | A video player with seeking, and the preview image as its poster |
| `audio/*`          | An audio player                                                  |
| `text/html`        | The page in a sandboxed frame with no access to the view         |
| Another media type | The preview when it has one of the types above, otherwise a note |

Every host also shows a **Download** link for the main file. Studio serves
rendered files with byte ranges, so media seeks without loading the whole
file. Style the host's parts from page CSS with `::part(toolbar)`,
`::part(download)`, `::part(problems)`, and `::part(content)`.

### Present files yourself

Markup inside a render host replaces the stock presentation, and the page fills
it from the host's render record. The toolbar and problems stay. A script that
runs after the first files are ready starts from `host.marimoRender`:

```html
<marimo-output render="scene.py">
  <video id="player" controls loop></video>
</marimo-output>
<script>
  const host = document.querySelector('marimo-output[render="scene.py"]');
  const player = document.querySelector("#player");
  const show = (record) => {
    const file = (path) => record.files.find((item) => item.path === path)?.url;
    player.src = file(record.main);
    player.poster = file(record.preview) ?? "";
  };
  if (host.marimoRender) show(host.marimoRender);
  host.addEventListener("marimo-output-ready", ({ detail }) => show(detail));
  host.addEventListener("marimo-output-updated", ({ detail }) => show(detail));
</script>
```

### Render records

`host.marimoRender` holds the files a render host shows, and the
`marimo-output-ready` and `marimo-output-updated` events carry the same record
as `detail`.

| Field      | Value                                                              |
| ---------- | ------------------------------------------------------------------ |
| `render`   | The render's source file                                           |
| `bundle`   | The content identity of the files                                  |
| `main`     | Path of the main file                                              |
| `preview`  | Path of the preview file, or `null`                                |
| `files`    | `{ path, mediaType, size, url }` for every file                    |
| `warnings` | Render warnings as diagnostics                                     |
| `absent`   | Targets the render read without a current result, shown as default |
| `regions`  | Parts of the files and the results they show, as `RenderRegion`    |

`marimo-output-ready` fires for the first files, `marimo-output-updated` when
the files change, and `marimo-output-error` on the first transition into
`error`, with `{ render, code, message, hint, diagnostics }`. Studio serves
rendered HTML, SVG, and XML files with a sandbox policy, so such a file opened
on its own runs in an opaque origin. A static export's web server sets its own
headers.

### Select parts of rendered files

A render's regions make the parts of its files selectable with
[Lens](https://marimo-team.github.io/marimo-lens/). Select a chart inside a
Typst PDF, a table cell, or a shape in a paused video, and Lens records the
cells that produced it, the value selector it shows, such as
`report.readings[6].occupancy`, and the source line that reads it, such as
`main.typ:85`. Selecting the file outside its regions records the results the
render reads, up to 64 of them.

Studio places a box over each region, in the host's light DOM, on these
surfaces:

| Surface                                      | Regions shown                                                    |
| -------------------------------------------- | ---------------------------------------------------------------- |
| A PDF page the host shows                    | The regions of that page                                         |
| An image or video the host shows             | The regions of the file                                          |
| An `img` or `video` in the page's own markup | The regions of the bundle file its `src` names                   |
| An element with `data-marimo-render-file`    | The regions of that file, on `data-marimo-render-page` for a PDF |

A video's regions follow its current time, and before it plays, its poster
shows the regions of the preview file. While Lens selects, Studio outlines each
region with a dashed line. Region boxes ignore the pointer otherwise, so
readers scroll, select PDF text, and use video controls as usual. A page that
draws a file itself, such as onto a canvas, marks the element that shows it:

```html
<marimo-output render="main.typ">
  <canvas data-marimo-render-file="main.pdf" data-marimo-render-page="1"></canvas>
</marimo-output>
```

Each box names its file part in `data-marimo-lens-media`, such as
`{"path":"main.pdf","page":2}` or `{"path":"animation.mp4","start":3.2,"end":4}`,
and Lens records it as the selection's `description.media`.

The preview runs in an opaque origin, so Lens captures no snapshot image of a
video frame and names that reason on the selection. The selection keeps its
notebook sources, label, and source line.

### Render values and runtimes

```typst
#import "marimo.typ": marimo_output, marimo_value

= Occupancy
Rooms in use: #marimo_value("summary.rooms", default: 0)

#marimo_output("occupancy_chart", width: 100%)
```

Values arrive in their
[JSON form](../guide/notebook-results.md#renders-read-json): a dataframe as a
list of row objects and a date as ISO 8601 text. A value the notebook has not
computed renders with the template's default. A value without a JSON form
fails with `render-value-not-json`, and a value too large to read fails with
`render-values-too-large`. An output arrives in the first media type
the render accepts and the value supports, such as PDF for a matplotlib figure
in a Typst report, drawn at the size the build measured at its placement. A
cell read receives the cell's output as marimo shows it, in the first accepted
type it carries, such as PNG for a matplotlib figure. An output or cell without
an accepted type, such as text or a table, renders with the template's
default, and the host notes `Showing the default for <target>.` A
`zero-python` export renders every output in every prepared state and stops
when one state's value has no accepted type.

A render reads its targets on its own, so a page can show a chart natively
while a render places the same chart as a PDF.

Each runtime supplies results from a different place:

| Runtime                      | Results come from                           | Files                                    |
| ---------------------------- | ------------------------------------------- | ---------------------------------------- |
| Python, edit and run mode    | The reader's kernel session, read by Studio | Rendered by Studio when a result changes |
| Browser, edit mode           | The notebook state in the editor tab        | Rendered by Studio when a result changes |
| Prepared, edit mode          | The prepared state the preview shows        | Rendered by Studio for each state change |
| Static export, `zero-python` | Each prepared notebook state                | One bundle per state, rendered at export |
| Browser, run mode            | Unavailable                                 | `render-results-unavailable` error       |
| Static export, `wasm`        | Unavailable                                 | `render-results-unavailable` error       |

In every runtime, a render reads its results between two notebook runs, so one
render never mixes results from different runs. A Prepared state holds one run
by construction. For published
views, Studio renders from session values and refuses values posted in run
mode with `render-values-unverified`.

## Presentation readiness

Wait for `html[data-marimo-studio-state="ready"]` before asserting the
application's result. This state covers Studio's runtime and mounted
projections. Custom charts, frameworks, and remote requests need their own
assertions. `data-marimo-studio-revision` on `<html>` holds the
committed presentation revision.

An uncaught error or unhandled rejection from a view file or inline module
script sets the state to `error` for the rest of that document. Studio shows
the first one with its built file and position, such as
`main.js:2:23: TypeError: <message>` or `inline script:2:23: ...`, and
`marimoStudio.diagnostics()` reports it with code `view-script-error`. Errors
from Studio's runtime, notebook files, and remote scripts, and browser warnings
such as ResizeObserver loop notices, leave the state unchanged.

A failed build leaves the state as it was and keeps the previous build on
screen. The page shows an alert that starts with `Latest build failed`, and
`marimoStudio.diagnostics()` lists the build's first error, such as
`view-build-failed`.

Host state is the lifecycle contract for one mounted result.
`marimo-studio:runtime-ready` fires on `document` when the notebook runtime
reaches its ready boundary, and `marimo-studio:idle` fires when the
presentation settles. Inspect the current DOM state when attaching after those
events.

Browser automation locates connected cell, output, and value hosts with
[`STUDIO_RESULT_SELECTOR`](python-api.md#studio-result-selector).

## Trace custom JavaScript rendering

[Select results with Lens](../guide/coding-agents.md#select-results-with-lens)
covers point-and-note feedback with producer context.

Use `mo-value`, `marimo-output`, and `marimo-cell` when they can render the
result directly. A custom chart or component keeps its notebook connection
through hidden projection hosts:

```html
<span id="rows-data" hidden mo-value="rows"></span>
<span id="summary-data" hidden mo-value="summary.total"></span>
<section data-marimo-lens-inputs="rows-data summary-data">
  <!-- JavaScript renders the chart here. -->
</section>
```

`data-marimo-lens-inputs` lists unique projection host IDs in the same
document, separated by spaces, and declares the region's complete notebook
input set. [Lens](https://marimo-team.github.io/marimo-lens/) reads the hosts'
resolved symbolic selectors and producing cells, so authors copy no runtime
metadata. References can also point to `marimo-output` or `marimo-cell` hosts.
Missing, duplicate, or unbound references make the region unavailable, and
references cannot chain through other annotated regions.

Alternatively, put hidden `mo-value` hosts directly inside their consuming
region. `STUDIO_RESULT_SELECTOR` matches those parents, annotated regions, and
direct projections. Pass it to `Lens(dom_selector=STUDIO_RESULT_SELECTOR)` to
select these results, or pass a custom CSS selector to choose other containing
regions.

Update references when JavaScript dependencies change, including transformed
inputs and portals. Set `aria-busy="true"` during asynchronous rendering and
clear it on completion. Lens retains value selectors and
producer context. It does not infer arbitrary JavaScript dataflow or pin
historical kernel values to captured pixels.

### Select individual results

Give each metric its own input host:

```html
<article class="metric">
  <span hidden mo-value="summary.events"></span>
  <span>Events</span>
  <strong><!-- JavaScript may format the value here. --></strong>
</article>
```

The hidden host makes the metric selectable by its exact field path. Use a
visible `mo-value` when native formatting suffices. Hidden hosts stay hidden
under ordinary layout styles. For dynamic rows
or thresholds, update the selector from the state that renders the result. For
non-JSON values, reference a hidden `marimo-output` host through
`data-marimo-lens-inputs`.

Dynamic selectors require the Python or Browser runtime, because Prepared
exports need a finite authored target set. Use `view export --runtime wasm`
when row or threshold selection generates paths at runtime.

A Prepared view can project a collection through a fixed selector and
reference that host from each row, with the row path in
`data-marimo-lens-detail` and a `data-marimo-lens-label`. The path is
descriptive context, and the resolved source selector remains the collection.

Browser calculations must reference their real kernel inputs, and can be
separate targets that share a dataframe. A canvas chart is a single surface
unless its renderer supplies finer DOM targets. Rendered files expose their
parts through [render regions](#select-parts-of-rendered-files).

### Selection labels

While selecting, Lens outlines the target element and attaches a compact label
to its edge. Studio supplies the resolved cell or variable name and its
producer. Custom regions inherit their source hosts' labels. Override the text
when a region needs a more specific name:

```html
<section
  data-marimo-lens-inputs="rows-data summary-data"
  data-marimo-lens-label="Revenue forecast"
  data-marimo-lens-detail="Monthly revenue · selected region"
>
  <!-- Custom rendering -->
</section>
```

Lens owns this plain-text label contract and its presentation. Labels leave
source links and the selection's notebook identity unchanged. Authored labels
on native projection hosts take precedence over Studio's defaults.

### Select authored page regions

Authored HTML inside `#app-shell` is selectable, including copy and layout
with no notebook inputs. Lens groups a click into the nearest section,
card, figure, or block and keeps the clicked child's text, path, and relative
bounds as a compact DOM hint. Native notebook outputs keep their own targets.

Set the grouping selector on the view shell:

```html
<main id="app-shell" data-marimo-lens-scope=".card, header, figure">
  <!-- Authored regions are selectable. -->
</main>
```

`data-marimo-lens-target` gives an authored region explicit target identity,
and `data-marimo-lens-render-source` identifies its source file:

```html
<header
  id="intro"
  data-marimo-lens-target
  data-marimo-lens-label="Introduction"
  data-marimo-lens-render-source='{"path":"index.html"}'
>
  <h1>Regional outlook</h1>
</header>
```

Keep the ID stable across rebuilds so Lens can reconnect feedback. A region
with no notebook inputs keeps its note and image with empty notebook
provenance. Use `data-marimo-lens-inputs` when the region consumes notebook
results.

### Project an authored Lens

Development previews reuse the Lens that marimo mounts in the notebook. To put
an authored Lens in another Python runtime view, define it in the notebook:

```python
from marimo_lens import Lens
from marimo_studio import STUDIO_RESULT_SELECTOR

studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)
None
```

The final `None` leaves the cell output empty. Project the value into the view
to place the Lens dock there:

```html
<marimo-output value="studio_lens"></marimo-output>
```

marimo skips its automatic Lens in a notebook that constructs its own, so
`studio_lens` is the notebook's only Lens.

The [Lens agent guide](https://marimo-team.github.io/marimo-lens/agents) defines
selection inspection, feedback, and resolution.
