---
title: Place notebook results on a page
description: Add complete cells, rendered Python objects, and JSON-compatible values to page source.
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

## Read a JSON-compatible value

```html
<strong mo-value="metrics.total"></strong>
```

Studio writes the selected text, number, boolean, array, object, or null value
into the element. Page JavaScript can also read the value and respond to later
updates.

Use this form when browser code will format, filter, group, or otherwise adapt
the value for one page.

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
unique cell names, 100 rendered objects, and 100 JSON-compatible values. A page
that exceeds a limit receives a diagnostic at the first affected element.
