---
title: Notebook result projections
description: Exact cell, output, value, selector, event, state, duplication, and data contracts for rendered views.
---

# Notebook result projections

A projection host places one notebook result in an authored view. Studio
resolves the host to one producer cell, runs its dependency closure in the
selected notebook runtime, and mounts the result in the host element.

| Host                            | Target                          | Browser result                                           |
| ------------------------------- | ------------------------------- | -------------------------------------------------------- |
| `<marimo-cell name="summary">`  | Named cell or Studio cell alias | Complete native cell presentation                        |
| `<marimo-output value="chart">` | Notebook value selector         | One value rendered by marimo's output renderer           |
| `mo-value="metrics.total"`      | Notebook value selector         | JSON value or Arrow-backed table exposed to browser code |

The Python runtime is configured as `server`. The Browser runtime is
configured as `wasm`. Both use the same authored projection hosts.

In HTML, close each projection host explicitly and place hosts beside each
other. Rendering a host replaces its contents. The build rejects nested hosts
and self-closing HTML elements such as `<h1 mo-value="total"/>`.

```html
<h1 mo-value="total"></h1>
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
```

## Complete cells

```html
<marimo-cell name="summary"></marimo-cell>
```

`name` accepts a native marimo cell name or an alias stored under
`[tool.marimo-studio.cells]`. The host receives the cell's native output,
controls, console output when `show_cell_logs` is enabled, error state, and
reactive updates.

One presentation can mount a cell target once. A second host for the same
target enters `data-state="error"` with diagnostic code
`duplicate-cell-host`.

## Rendered outputs

```html
<marimo-output value="chart"></marimo-output>
```

`value` selects a Python value, so assign the figure or object to a notebook
variable, such as `chart = plot_revenue(rows)`. marimo renders the selected
object through its native output renderer and keeps the result current when its
producer reruns.

`accept` shows the value as an image instead. List image types in order of
preference, separated by spaces or commas:

```html
<marimo-output value="chart" accept="image/svg+xml image/png"></marimo-output>
```

Studio renders the value in the first listed type it supports through
marimo-export's
[`represent()`](https://marimo-team.github.io/marimo-export/reference/python/values).
The notebook's own output settings stay unchanged, so the notebook can show a
PNG while the page shows a sharp SVG.

- A page host accepts `image/svg+xml`, `image/png`, `image/jpeg`, and
  `image/gif`, the images marimo's output renderer shows.
- A matplotlib figure or axes renders as SVG or PNG. A PNG displays at the size
  marimo shows the figure, with twice the pixels, so it stays sharp on
  high-density screens.
- An Altair chart renders as SVG or PNG with `vl-convert-python`. The Browser
  runtime has no `vl-convert-python`, so leave `accept` off to show the
  interactive chart there. Read the chart itself, not a `mo.ui.altair_chart`
  wrapper.
- Other values use their display methods.
- A figure keeps the style it was drawn with, including the dark style marimo
  applies when the editor uses its dark theme.

A value without an accepted type puts the host in `data-state="error"` with
code `output-media-unavailable`. Studio reads `accept` when it builds the view,
so a script that changes the attribute later has no effect.

A view reads each output target in one form. Every literal host that names a
target in `value`, and every document that reads it, lists the same media types. A different list reports `output-accept-conflict` at its source
location. A host with `data-marimo-allow="*"` shows each target in the form
its literal hosts declare, and an `accept` on that host reports
`projection-accept-invalid`.

One presentation can mount an output target once. A second host for the same
target enters `data-state="error"` with diagnostic code
`duplicate-output-host`.

## Browser values

```html
<strong mo-value="metrics.total"></strong>
```

Studio writes a scalar value into the element's text content. It renders
`null` as an empty string and renders arrays and objects as compact JSON. The
host also exposes the decoded value through its non-enumerable, read-only
`marimoValue` property:

```js
const host = document.querySelector('[mo-value="metrics.total"]');

host.addEventListener("marimo-value-updated", (event) => {
  console.log(event.detail.value);
  console.log(host.marimoValue);
});
```

Several `mo-value` hosts may select the same target. Each host receives its own
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
with `_`. Bracket indexes must be JavaScript safe integers. A selector may
contain at most 64 path steps and 4,096 UTF-8 bytes. Studio parses selectors
with marimo-export's
[`ValueSelector`](https://marimo-team.github.io/marimo-export/reference/python/values#valueselector),
so a view and a Prepared export accept the same selectors. See
[Limits](limits.md) for the complete projection budget.

### Value codecs

| Codec          | JavaScript value                                         | Contract                                                                       |
| -------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `json-v1`      | `null`, boolean, number, string, array, or object        | `marimoValue` returns the decoded JSON-compatible value                        |
| `arrow-ipc-v1` | [Flechette](https://github.com/uwdata/flechette) `Table` | `marimoValue` returns the table with its source bytes and fingerprint attached |

A `json-v1` value encodes within 1,000,000 bytes and an `arrow-ipc-v1` value
within 64 MiB. See [Runtime payloads](limits.md#runtime-payloads) for the
per-read budgets.

Studio decodes Arrow tables with Flechette's default extraction options.
Integer columns, including 64-bit integers, read as numbers, and reading a
64-bit value beyond `Number.MAX_SAFE_INTEGER` throws. Booleans and strings keep
their JavaScript types, list cells read as arrays, and dates and timestamps read
as epoch milliseconds. `table.toArray()` returns plain row objects.

React starters export `useMarimoValue()` and `getMarimoDataSource()` from
`src/lib/use-marimo-value.ts`. Svelte starters export
`observeMarimoValue()` and `getMarimoDataSource()` from
`src/lib/marimo-value.ts`. `getMarimoDataSource(table)` returns the codec,
fingerprint, and immutable
[Arrow IPC](https://arrow.apache.org/docs/format/Columnar.html#serialization-and-interprocess-communication-ipc)
bytes attached to an Arrow-backed table. Arrow IPC is a columnar data
interchange format.

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

Value hosts retain their previous `marimoValue` while entering `loading` or
`stale`. A terminal value error clears the property and dispatches
`marimo-value-error`.

### Cell events

| Event                 | Dispatch                                        | Detail fields                                                         |
| --------------------- | ----------------------------------------------- | --------------------------------------------------------------------- |
| `marimo-cell-ready`   | First transition to `ready`                     | `alias`, `runtimeId`, `outputMime`, or diagnostic fields when present |
| `marimo-cell-updated` | A later transition to `ready`                   | Same shape as `marimo-cell-ready`                                     |
| `marimo-cell-error`   | First transition into the current `error` state | `alias`, `runtimeId`, `code`, `message`, `hint` when present          |

### Output events

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
boundaries. Shadow DOM is a browser boundary that encapsulates a component's
internal document tree. Listen on the host for one projection or on `document`
for the presentation.

## Authored sites and dynamic targets

A view provider reports each authored projection host as a projection site.
Studio adds `data-marimo-studio-site` to the host in the build snapshot, and
the attribute carries the site into the built page. Leave that attribute to
Studio.

A site with a finite target set can request those targets. A site with targets
`"*"` permits a dynamic target of the declared kind.
Built-in React and Svelte providers infer finite targets from literals and
bounded constant expressions. Add `data-marimo-allow="*"` when a framework
expression intentionally selects its target at runtime:

```tsx
<marimo-cell name={selectedName} data-marimo-allow="*" />
```

The HTML provider authorizes each host for its authored target. Add the same
wildcard when page JavaScript changes the host's selector:

```html
<span id="details" hidden mo-value="details.first" data-marimo-allow="*"></span>
```

An unbounded expression without that literal wildcard produces
`projection-target-unbounded`. Any other `data-marimo-allow` value produces
`projection-wildcard-invalid`. Static validation checks finite targets. Browser
assertions verify the rendered results of a dynamic site.

Changing `name`, `value`, or `mo-value` releases the prior target and resolves
the same DOM instance against the new target. Removing the host releases its
projection ownership.

## Rendered documents

A rendered document, such as the PDF that the Typst provider compiles, reads
notebook values and outputs when Studio renders it. The view page shows the
document in a `<marimo-document>` viewer. Studio renders it again when a value
or output it reads changes.
The viewer keeps the last document on screen while a new one renders and shows
render errors beside it.

```typst
#import "marimo.typ": marimo_output, marimo_value

= Occupancy
Rooms in use: #marimo_value("summary.rooms", default: 0)

#marimo_output("occupancy_chart", width: 100%)
```

Values reach the renderer as portable JSON. A table value, such as a
dataframe, fails with `render-value-not-json`. Convert it in the notebook, for
example with `df.to_dicts()`. Outputs reach the renderer in the first media
type the document accepts that the value supports, such as PDF for a
matplotlib figure in a Typst report. An output without an accepted type
renders with the template's default, and the viewer names it. A `zero-python`
export renders every output in every prepared state, so the export stops when
one state's value has no accepted type. A cell read receives the cell's output
as marimo shows it, in the first accepted type the output carries, such as PNG
for a matplotlib figure. A cell whose output has no accepted type, such as
text or a table, renders with the template's default.

Each runtime supplies values from a different place:

| Runtime                      | Values come from                            | Document                                   |
| ---------------------------- | ------------------------------------------- | ------------------------------------------ |
| Python, edit and run mode    | The reader's kernel session, read by Studio | Rendered by Studio for each value change   |
| Browser, edit mode           | The notebook state in the editor tab        | Rendered by Studio for each value change   |
| Prepared, edit mode          | The prepared state the preview shows        | Rendered by Studio for each state change   |
| Browser, run mode            | Unavailable                                 | The document rendered at build time        |
| Static export, `zero-python` | Each prepared notebook state                | One document per state, rendered at export |
| Static export, `wasm`        | Unavailable                                 | The document rendered at build time        |

Outputs and cells follow the same rows. They come from the reader's kernel
session, from the preview's `marimo-output` and `marimo-cell` hosts, or from
each prepared state.

Studio renders documents from session values for published views and refuses
values posted in run mode with `render-values-unverified`. Where no current
values reach the document, the viewer shows the build-time document with the
note `Showing the document without current notebook values.` A `wasm` export,
and a `zero-python` export state without a rendition, show the same note.

## Presentation readiness

Wait for `html[data-marimo-studio-state="ready"]` before asserting the
application's expected result. This state covers Studio's runtime and mounted
projections. Custom chart, framework, and remote-request completion need their
own application assertions. Read `data-marimo-studio-revision` on `<html>` for
the committed presentation revision.

An uncaught error or unhandled rejection from a view file or inline module
script sets the state to `error` for the rest of that document. Studio shows
the first one with its built file and position, such as
`main.js:2:23: TypeError: <message>`, or `inline script:2:23: ...`, and
`marimoStudio.diagnostics()` reports it with the `view-script-error` code.
Studio's runtime, notebook files, remote scripts, and browser warnings such as
ResizeObserver loop notices leave the state unchanged.

Projection host state is the lifecycle contract for one mounted result.
`marimo-studio:runtime-ready` fires on `document` when the notebook runtime
reaches its ready boundary. `marimo-studio:idle` fires when Studio's presentation
reaches a settled state. Inspect the current DOM state when attaching after
those events.

Use [`STUDIO_RESULT_SELECTOR`](python-api.md#studio-result-selector) to locate
connected cell, output, and value hosts in browser automation.

## Trace custom JavaScript rendering

For point-and-note feedback with producer context, follow
[Select results with Lens](../guide/coding-agents.md#select-results-with-lens).

Prefer `mo-value`, `marimo-output`, and `marimo-cell` when they can render the
result directly. For a custom chart or component, retain its connection to the
notebook through the existing projection hosts:

```html
<span id="rows-data" hidden mo-value="rows"></span>
<span id="summary-data" hidden mo-value="summary.total"></span>
<section data-marimo-lens-inputs="rows-data summary-data">
  <!-- JavaScript renders the chart here. -->
</section>
```

`data-marimo-lens-inputs` lists unique projection host IDs, separated by spaces, in
the same document. It declares the region's complete notebook input set.
[Lens](https://marimo-team.github.io/marimo-lens/) reads the hosts' resolved
symbolic selectors and producing cells. Authors do not copy runtime metadata.
References can also point to `marimo-output` or `marimo-cell` hosts.
Missing, duplicate, or unbound references make the region unavailable.
References cannot chain through other annotated regions.

Alternatively, put existing hidden `mo-value` hosts directly inside their
consuming region. `STUDIO_RESULT_SELECTOR` includes those parents and explicitly
annotated regions, as well as direct projections. Pass it to
`Lens(dom_selector=STUDIO_RESULT_SELECTOR)` to select these results. A custom
Lens CSS selector can choose other containing regions.

Keep references current when JS dependencies change, including transformed
inputs and portals. Use `aria-busy="true"` while asynchronous rendering is
incomplete and clear it on completion. Lens retains value selectors and producer
context. It does not infer arbitrary JS dataflow or pin historical kernel
values to captured pixels.

### Select individual results

Give each metric its own inputs instead of assigning only the entire row or page:

```html
<article class="metric">
  <span hidden mo-value="summary.events"></span>
  <span>Events</span>
  <strong><!-- JavaScript may format the value here. --></strong>
</article>
```

The hidden host makes the metric selectable with its exact symbolic field path.
Use a visible `mo-value` directly when native formatting is sufficient. Hidden
projection hosts stay hidden even under ordinary application layout styles.
For dynamic rows or thresholds, update the projection selector with the same
state used to render the result. For non-JSON values, reference a hidden
`marimo-output` host through `data-marimo-lens-inputs`.

Dynamic selectors require the Python or Browser runtime. Prepared exports need
a finite authored target set. Use `view export --runtime wasm` when row or
threshold selection generates paths at runtime.

Prepared views can project a collection through a fixed selector and reference
that host from each row. Add the selected row path with `data-marimo-lens-detail`
and a `data-marimo-lens-label`. The path supplies descriptive selection context.
The resolved source selector remains the collection.

Browser calculations must reference their real kernel inputs. They can be
separate targets even when they share a dataframe. Canvas charts and PDF pages
are single surfaces unless their renderer supplies finer DOM targets.

### Selection labels

While Lens is selecting a target, it outlines the element and attaches a compact
label to its edge. Studio supplies the resolved cell or variable name and its
producer automatically. Custom regions inherit the labels of their source hosts.
Override the display text when a region needs a more specific name:

```html
<section
  data-marimo-lens-inputs="rows-data summary-data"
  data-marimo-lens-label="Revenue forecast"
  data-marimo-lens-detail="Monthly revenue · selected region"
>
  <!-- Custom rendering -->
</section>
```

Lens owns this plain-text label contract and presentation. The labels do not
replace source links or change the selection's notebook identity. Authored labels
on native projection hosts also take precedence over Studio's defaults.

### Select authored page regions

Studio makes authored HTML inside `#app-shell` selectable, including copy and
layout with no notebook inputs. Lens groups a click into the nearest section,
card, figure, or block. It retains the clicked child's text, path, and relative
bounds as a compact DOM hint. Native notebook outputs retain their own targets.

Set the grouping selector on the view shell:

```html
<main id="app-shell" data-marimo-lens-scope=".card, header, figure">
  <!-- Authored regions are selectable. -->
</main>
```

Use `data-marimo-lens-target` to give an authored region explicit target identity
and `data-marimo-lens-render-source` to identify its source file:

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

Keep the ID stable across rebuilds so Lens can reconnect feedback. An authored
region with no notebook inputs retains its note and image with empty notebook
provenance. Use `data-marimo-lens-inputs` when the region consumes notebook
results.

### Project an authored Lens

Development previews reuse the Lens that marimo mounts in the notebook. To put
an explicitly authored Lens in another Python runtime view, define it in the notebook:

```python
from marimo_lens import Lens
from marimo_studio import STUDIO_RESULT_SELECTOR

studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)
None
```

The final `None` leaves the notebook cell output empty. Project the value into
the view to place the Lens dock there:

```html
<marimo-output value="studio_lens"></marimo-output>
```

marimo skips its automatic Lens in a notebook that constructs its own Lens, so
`studio_lens` is the notebook's only Lens.

The [Lens agent guide](https://marimo-team.github.io/marimo-lens/agents) defines
selection inspection, feedback, and resolution.
