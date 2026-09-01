---
title: Place notebook results in a view
description: Use complete cells, rendered outputs, and browser values in view source documents.
---

# Place notebook results in a view

View source requests notebook results through projection hosts. Choose the host
that matches what the frontend needs:

| Result          | View source                       | Use it for                                                          |
| --------------- | --------------------------------- | ------------------------------------------------------------------- |
| Complete cell   | `<marimo-cell name="summary">`    | Native controls, output, logs, errors, and reactive behavior        |
| Rendered output | `<marimo-output value="chart">`   | One Python value rendered through marimo's native output system     |
| Browser value   | `<span mo-value="metrics.total">` | JSON-compatible data or an eager dataframe consumed by browser code |

All projection hosts belong inside `#app-shell`.

## Place a complete cell

Name the producing cell in the notebook:

```python
@app.cell
def sport_control(athletes, mo):
    sport = mo.ui.dropdown(
        options=athletes["sport"].unique().sort().to_list(),
        label="Sport",
    )
    sport
    return (sport,)
```

Place the cell by name:

```html
<marimo-cell name="sport_control"></marimo-cell>
```

The host preserves the native control and its complete cell lifecycle. A
control change reruns dependent notebook cells and updates their mounted
results.

## Render one notebook output

Use `marimo-output` when marimo should choose the native renderer:

```html
<marimo-output value="selected_roster"></marimo-output>
```

The Rio athletes report uses this host for the filtered Polars table. It uses
`mo-value="top_sports"` separately so browser JavaScript can draw the
participation chart.

Output selectors can traverse attributes, dictionary keys, and list items:

```text
report.chart
results["overview"]
rows[0]
```

## Read a browser value

`mo-value` assigns the current value to `host.marimoValue` and dispatches an
event when the value changes:

```html
<span id="summary-data" hidden mo-value="summary"></span>
<output id="summary-total"></output>

<script type="module">
  const host = document.querySelector("#summary-data");
  const output = document.querySelector("#summary-total");

  const render = (value) => {
    output.value = value.total.toLocaleString();
  };

  host.addEventListener("marimo-value-updated", (event) => {
    render(event.detail.value);
  });

  if (host.marimoValue !== undefined) {
    render(host.marimoValue);
  }
</script>
```

Register the listener before reading `marimoValue`. `undefined` means the
value has not arrived or cannot currently be read. JSON `null` remains a valid
value. Listen for `marimo-value-error` when the view needs a local recovery
state.

React starters provide `useMarimoValue`. Svelte starters provide
`observeMarimoValue`.

## Pass a dataframe to JavaScript

An eager dataframe reaches browser code as a
[Flechette](https://github.com/uwdata/flechette) `Table`. Studio encodes the
dataframe as [Arrow IPC](https://arrow.apache.org/docs/format/Columnar.html#serialization-and-interprocess-communication-ipc),
a columnar data interchange format, and decodes it before updating the host.

```js
const chartRows = table.select(["region", "revenue"]).toArray();
```

Treat the shared table as immutable. Keep data columnar while selecting fields
or passing it to a column-oriented library. Call `toArray()` at a consumer that
needs row objects.

The Browser runtime requires browser-compatible dataframe and Arrow writer
packages. Materialize lazy or remote queries in the notebook before projecting
them.

## Use dynamic projection targets deliberately

React and Svelte providers inspect literal targets and finite arrays during the
build. Keep those targets explicit when possible:

```tsx
{
  ["summary", "details"].map((name) => <marimo-cell key={name} name={name} />);
}
```

When runtime state can choose any notebook target, declare that broader
authorization on the host:

```tsx
<marimo-cell name={selectedName} data-marimo-allow="*" />
```

`data-marimo-allow="*"` permits that source location to request any valid
target of the same projection kind. Use it at the narrowest dynamic host. A
computed target without the declaration fails provider inspection.

## Name and validate targets

A semantic native cell name is the direct target. Give an anonymous cell a
stable alias when renaming it is unsuitable:

```console
marimo-studio notebook bind summary --target analysis.py --cell 12
```

The alias belongs to the notebook and is available to every view.

Validate source and notebook names without executing the notebook:

```console
marimo-studio validate dashboard --target analysis.py
```

Execute the complete notebook, then check the view's selected projections:

```console
marimo-studio validate dashboard \
  --target analysis.py \
  --level runtime
```

Runtime validation can perform file, network, database, and other work from any
notebook cell. Use it with trusted notebooks. See the
[Projection DOM API](../reference/projections.md) for event payloads, state
attributes, duplicate-host rules, and limits.
