---
title: Place notebook results on a page
description: Add complete cells, rendered Python objects, and browser values to page source.
---

# Place notebook results on a page

Keep data access and computation in the notebook. Page source chooses which
results the audience sees and where they appear.

## Place a complete cell

```html
<marimo-cell name="summary"></marimo-cell>
```

The page receives the cell's displayed output, controls, and standard streams.
Marimo continues to run its reactive dependencies.

Use a complete cell when the notebook already presents the result the way the
page needs it.

## Render one Python object

```html
<marimo-output value="chart"></marimo-output>
```

Marimo renders `chart` with the same rich-output system used by the notebook.
You can select a nested item or attribute:

```html
<marimo-output value='results["overview"]'></marimo-output>
```

Use this form when the page needs one object rather than the complete producing
cell.

## Read a value in browser code

```html
<strong mo-value="metrics.total"></strong>
```

Studio writes a selected JSON-compatible text, number, boolean, array, object,
or null value into the element. Page JavaScript can read the current value from
`host.marimoValue` and listen for later updates.

Use this form when browser code will format, filter, group, or otherwise adapt
the value for one page.

### Read a dataframe as a table

An eager dataframe reaches browser code as a shared
[Flechette `Table`](https://github.com/uwdata/flechette). Studio encodes the
dataframe as Arrow IPC and decodes it once before assigning the table to
`host.marimoValue` and `event.detail.value`. Treat the shared table as
immutable.

```html
<span id="orders-data" hidden mo-value="orders"></span>
<output id="order-count"></output>

<script type="module">
  const host = document.querySelector("#orders-data");
  const count = document.querySelector("#order-count");

  const render = (table) => {
    count.value = `${table.numRows} orders`;
  };

  host.addEventListener("marimo-value-updated", (event) => {
    render(event.detail.value);
  });

  if (host.marimoValue !== undefined) {
    render(host.marimoValue);
  }
</script>
```

The table keeps Arrow data in columnar form. Its core accessors cover the common
browser paths:

- `numRows`, `numCols`, `names`, and `schema` describe the table.
- `get(index)` reads one row. Iteration scans row objects.
- `getChild(name)` reads one column.
- `select(names)` returns a table with selected columns.
- `toColumns()` extracts arrays by column.
- `toArray()` materializes an array of row objects.

Keep the table columnar while filtering columns or passing data to a
column-oriented library. Materialize rows at the consumer boundary:

```js
const chartRows = table.select(["region", "revenue"]).toArray();
```

React and Svelte starter helpers export `getMarimoDataSource(table)`. It returns
the table's codec, fingerprint, and shared Arrow IPC bytes. Treat the bytes as
immutable, or copy them before mutating them. The descriptor is stored under
`MARIMO_DATA_SOURCE = Symbol.for("marimo-studio.data-source")`.

Automatic table projection applies to eager dataframe values that the active
Python environment can write as Arrow IPC. Pandas dataframes may require
PyArrow. Materialize lazy or remote dataframe queries in the notebook before
selecting them with `mo-value`.

WebAssembly notebooks must include browser-compatible dataframe and Arrow writer
packages. Their encoded values remain subject to Studio's value byte limit.

React starters export `MarimoTable` with `useMarimoValue`. Svelte starters
export the same table contract with `observeMarimoValue`.

## Name a result

Native marimo cell names are the most direct page targets:

```python
@app.cell
def summary(data):
    result = data.describe()
    result
    return (result,)
```

An existing anonymous cell can receive a stable alias:

```console
marimo-studio notebook bind summary --target analysis.py --cell 12
```

The alias belongs to the notebook and is available to every page.

## Select nested values

Object and value references begin with a notebook variable. Dot and bracket
selection can then reach nested data:

```text
metrics.total
results["overview"]
rows[0].label
```

Calls, operators, slices, and private attributes are outside this reference
syntax. Studio reports the source location when a reference is malformed,
missing, or ambiguous.

## Change the selected result in browser code

React and Svelte pages can choose a result from a constant list or record. The
build records those possible names, then Studio checks the chosen name against
the current notebook before rendering it.

A page can also move an existing result element. The control, widget, or output
keeps its owner while the element moves. A second complete-cell or rendered-
object element for the same result reports a duplicate diagnostic.

## Validate the page references

Check source and notebook names without running the notebook:

```console
marimo-studio validate dashboard --target analysis.py
```

Add `--level runtime` when validation should execute the complete notebook and
inspect the selected results:

```console
marimo-studio validate dashboard --target analysis.py --level runtime
```

Runtime validation can perform the notebook's configured file, network,
database, and data access.

Studio bounds one rendered page to 512 active result elements, including 256
unique cell names, 100 rendered objects, and 100 value projections. A page that
exceeds a limit receives a diagnostic at the first affected element.
