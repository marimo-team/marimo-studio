---
title: Place notebook results in a view
description: Use complete cells, rendered Python objects, and browser values in custom frontend source.
---

# Place notebook results in a view

The athlete report uses all three projection forms in one document:

```html
<marimo-cell name="sport_control"></marimo-cell>

<strong mo-value="athlete_summary.athletes"></strong>

<marimo-output value="top_sports"></marimo-output>
```

Changing the sport control reruns its dependent notebook cell. Studio updates
the scalar total and rendered Polars table without rebuilding the frontend.

## Choose the projection form

| Notebook result     | View source                       | Use it when                                                                 |
| ------------------- | --------------------------------- | --------------------------------------------------------------------------- |
| Complete cell       | `<marimo-cell name="summary">`    | The view needs the cell output, controls, logs, or errors                   |
| One rendered object | `<marimo-output value="chart">`   | Marimo should render one Python object with its native rich-output system   |
| Browser value       | `<span mo-value="metrics.total">` | JavaScript will format or pass a JSON-compatible value to a browser library |

Object and value selectors can read attributes, dictionary keys, and list
items:

```text
metrics.total
results["overview"]
rows[0].label
```

Calls, operators, slices, and private attributes are outside the selector
syntax.

## React to a browser value

Register the update listener before reading the current value:

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

`undefined` means the value has not arrived or cannot currently be read. JSON
`null` remains a valid value. Listen for `marimo-value-error` when the view
needs a local recovery state.

React starters provide `useMarimoValue`. Svelte starters provide
`observeMarimoValue`.

## Pass a dataframe to JavaScript

An eager dataframe reaches browser code as a shared Flechette `Table`. Studio
encodes the dataframe as Arrow IPC and decodes it before assigning
`host.marimoValue` and `event.detail.value`.

```js
const chartRows = table.select(["region", "revenue"]).toArray();
```

Keep the table columnar while selecting columns or passing data to a
column-oriented library. Materialize row objects at the consumer boundary.

The athlete explorer reads `athlete_facts` as Arrow IPC, then inserts a copy
into DuckDB-WASM for Mosaic queries. The occupancy views pass projected tables
to ECharts and Recharts.

WebAssembly notebooks must include browser-compatible dataframe and Arrow
writer packages. Materialize lazy or remote queries in the notebook before
projecting them.

## Name a result

A semantic native cell name is the most direct target:

```python
@app.cell
def summary(data):
    result = data.describe()
    result
    return (result,)
```

Give an existing anonymous cell a stable alias when renaming it is not
appropriate:

```console
marimo-studio notebook bind summary --target analysis.py --cell 12
```

The alias belongs to the notebook and is available to every view.

## Validate projections

Check source and notebook names without running the notebook:

```console
marimo-studio validate dashboard --target analysis.py
```

Execute the notebook and inspect selected results with runtime validation:

```console
marimo-studio validate dashboard \
  --target analysis.py \
  --level runtime
```

Runtime validation can perform the notebook's configured file, network,
database, and data access.
