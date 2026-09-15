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
| `<marimo-output value="chart">` | Notebook value selector         | One value rendered by Marimo's output renderer           |
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

`name` accepts a native Marimo cell name or an alias stored under
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

`value` selects a Python value. Marimo renders the selected object through its
native output renderer and keeps the result current when its producer reruns.

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
contain at most 64 path steps and 4,096 UTF-8 bytes. See [Limits](limits.md) for
the complete projection budget.

### Value codecs

| Codec          | JavaScript value                                         | Contract                                                                       |
| -------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `json-v1`      | `null`, boolean, number, string, array, or object        | `marimoValue` returns the decoded JSON-compatible value                        |
| `arrow-ipc-v1` | [Flechette](https://github.com/uwdata/flechette) `Table` | `marimoValue` returns the table with its source bytes and fingerprint attached |

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

A view provider records each authored projection as a mount declaration. A
build adds `data-marimo-studio-site` to the corresponding artifact host. View
source should leave that attribute to the provider build.

A mount with a finite `allowed_targets` set can request those targets. A mount
with `allowed_targets=None` permits a dynamic target of the declared kind.
Bundled React and Svelte providers infer finite targets from literals and
bounded constant expressions. Add `data-marimo-allow="*"` when a framework
expression intentionally selects its target at runtime:

```tsx
<marimo-cell name={selectedName} data-marimo-allow="*" />
```

An unbounded expression without that literal wildcard produces
`projection-target-unbounded`. Any other `data-marimo-allow` value produces
`projection-wildcard-invalid`. Static validation checks finite targets. Browser
validation verifies the active instances of a dynamic site.

Changing `name`, `value`, or `mo-value` releases the prior target and resolves
the same DOM instance against the new target. Removing the host releases its
projection ownership.

## Presentation readiness

`marimo-studio:runtime-ready` fires on `document` when the selected notebook
runtime has reached its ready boundary. `marimo-studio:idle` fires after the
rendered page reaches a settled observation state. Projection host state remains
the exact contract for one mounted result.

Use [`STUDIO_RESULT_SELECTOR`](python-api.md#studio-result-selector) to locate
connected cell, output, and value hosts in browser automation.

## Trace custom JavaScript rendering

For point-and-note feedback with producer context, follow
[Set up Marimo Lens](../guide/coding-agents.md#point-to-a-result-with-marimo-lens).

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
the same document. It declares the region's complete notebook input set. Lens
reads the hosts' resolved symbolic selectors and producing cells; authors do not
copy runtime metadata. References can also point to `marimo-output` or
`marimo-cell` hosts. Missing, duplicate, or unbound references make the region
unavailable. References cannot chain through other annotated regions.

Alternatively, put existing hidden `mo-value` hosts directly inside their
consuming region. `STUDIO_RESULT_SELECTOR` includes those parents and explicitly
annotated regions, as well as direct projections. Pass it to
`Lens(dom_selector=STUDIO_RESULT_SELECTOR)` to select these results. A custom
Lens CSS selector can choose other containing regions.

Keep references current when JS dependencies change, including transformed
inputs and portals. Use `aria-busy="true"` while asynchronous rendering is
incomplete and clear it on completion. Lens retains value selectors and producer
context; this does not infer arbitrary JS dataflow or pin historical kernel
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
a finite authored target set; use `view export --runtime wasm` when row or
threshold selection generates paths at runtime.

Browser calculations must reference their real kernel inputs. They can be
separate targets even when they share a dataframe. Canvas charts and PDF pages
are single surfaces unless their renderer supplies finer DOM targets.

### Labels while selecting a target

While Lens is selecting a target, it outlines the element and attaches a compact
label to its edge. Studio supplies the resolved cell or variable name and its
producer automatically. Custom regions inherit the labels of their source hosts.
Override the display text when a region needs a more useful name:

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
