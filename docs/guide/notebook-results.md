---
title: Use notebook results
description: Place complete cells, rendered Python objects, values, and controls in custom frontend layouts.
---

# Use notebook results

Keep computation in named Marimo cells. Frontend source decides where each
result appears.

## Complete cell

```html
<marimo-cell name="summary"></marimo-cell>
```

This mounts the cell's outputs, controls, and standard streams according to the
notebook configuration. Reactive dependencies continue to run through Marimo.

## Rendered Python object

```html
<marimo-output value="chart"></marimo-output>
```

Marimo formats the selected Python object through its normal rich-output
renderer. Nested item and attribute selectors are supported:

```html
<marimo-output value='results["overview"]'></marimo-output>
```

## JSON-compatible value

```html
<strong mo-value="metrics.total"></strong>
```

The runtime writes the selected value into the element. Use this form for text,
numbers, booleans, arrays, objects, and null.

## Dynamic layouts

Literal mounts work with every provider. Providers with source analyzers may
also advertise finite target sets from constant source data.

The frontend may retarget and move an existing mount. Studio keeps the mount
owner while the DOM node moves and validates each new target against the
declaration and current notebook graph.

An analyzer may support explicit wildcard access when source cannot provide a
finite set. An unresolved expression outside that provider capability is a
source diagnostic. The selected provider guide defines its dynamic-target
syntax.

## Controls

Controls inside mounted cells remain native Marimo controls. Server views use
the live kernel. Browser-worker views synchronize compatible control state
inside the page. Several browser windows keep separate sessions while sharing
the same published frontend files.

## Naming targets

Prefer native Marimo cell names:

```python
@app.cell
def summary(data):
    description = data.describe()
    description
    return (description,)
```

Bind an existing anonymous cell when renaming it is impractical:

```console
marimo-studio bind analysis.py --cell 12 --as summary
```

## Validate targets

```console
marimo-studio validate analysis.py --view dashboard --level static
marimo-studio validate analysis.py --view dashboard --level runtime
```

Static validation checks source declarations and notebook resolution. Runtime
validation starts the complete notebook reactive app in an isolated process,
then checks the selected view's projected cells, rendered outputs, and
JSON-compatible values. It reports missing, disabled, errored, oversized, or
unrenderable results.

[Projection reference](../reference/projections.md) defines selectors and
diagnostics. [Runtimes](../reference/runtimes.md) defines server and browser
execution.
