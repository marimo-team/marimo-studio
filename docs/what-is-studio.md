---
title: What is Studio?
description: Turn one reactive marimo notebook into named web views for different purposes.
---

# What is Studio?

Marimo Studio lets one saved marimo notebook back several named web views. The
notebook is the analytical model. Each view is a frontend project that presents
selected notebook results for a particular job.

The notebook owns data access, Python computation, controls, and reusable
results. A view owns its HTML, CSS, JavaScript, layout, visual encoding, wording,
and browser interaction.

## One notebook, many views

The same analysis can support an explorer, monitor, report, review, or
presentation. Each view has its own source files, browser dependencies, build,
route, and last successful artifact.

The Building occupancy notebook supports a facilities monitor and an
interactive model review. Switch between the two views, then open **Notebook**
to inspect the shared sensor calculations and threshold evaluation behind them.

<StudioExample family="occupancy" />

A shared analytical change belongs to the notebook. A change made for one job
belongs to its view. [One notebook, many views](guide/views.md) explains how
these projects share computation while keeping their frontend work independent.

[Open the complete Building occupancy example](examples/occupancy.md) to trace
its controls, metrics, error evidence, and view source.

## Named results connect Python to the view

All Python computation runs in the notebook. View source references notebook
results by name:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

A complete cell preserves its controls and reactive output. A rendered output
uses marimo's native renderer. A browser value gives frontend code
JSON-compatible data or an Arrow-backed dataframe.

[Place notebook results in a view](guide/notebook-results.md) describes each
projection form and its update events.

## Edit the notebook and view together

Studio adds three connected surfaces to the marimo editor:

- **Notebook** for Python and reactive computation
- **Source** for the selected view's frontend files
- **Preview** for the current built artifact

Saving Source rebuilds Preview. A failed build keeps the last successful view
available while Studio reports the source problem.

[Create your first view](guide/getting-started.md) opens this workspace from a
saved notebook. [Why Studio?](why-studio.md) explains why the notebook remains
the durable source behind every view.
