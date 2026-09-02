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
