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

## Read the model through one notebook

The Building occupancy notebook defines sensor baselines, anomaly candidates,
an occupancy score, and a threshold sweep. Its **Monitor** and **Model review**
views present those results for two different decisions:

<StudioExample family="occupancy" />

Change **Signal** in Monitor. Marimo reruns the cells that produce the selected
series, then Studio updates the ECharts view without rebuilding its frontend.
Move the threshold in Model review and the same notebook score drives its
accuracy, precision, recall, and error evidence.

Each view has separate HTML, CSS, JavaScript, and a last successful browser
artifact. Saving Monitor source builds a new Monitor artifact. Model review and
the active notebook session remain available during that build.

This example has three independently changing layers:

| Action                    | Changes                                                                | Remains available                      |
| ------------------------- | ---------------------------------------------------------------------- | -------------------------------------- |
| Save view source          | Studio builds and publishes a new immutable artifact                   | Notebook session and current results   |
| Change a notebook control | Marimo reruns affected Python cells and Studio updates mounted results | View source and artifact               |
| Switch runtime            | The notebook runs in Python or a browser worker                        | View source and artifact               |
| Repair a failed build     | Studio replaces Preview after the next valid artifact publishes        | Last successful artifact during repair |

Preview combines one published artifact with the selected notebook runtime. A
source revision identifies editable files, an artifact revision identifies
built browser files, and a presentation revision identifies the artifact and
notebook state shown together.

## One notebook, many views

The same analysis can support an explorer, monitor, report, review, or
presentation. Each view has its own source files, browser dependencies, build,
route, and last successful artifact.

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
