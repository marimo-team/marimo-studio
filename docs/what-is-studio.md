---
title: What is Studio?
description: Turn one reactive Marimo notebook into named web views for different jobs.
---

# What is Studio?

Marimo Studio turns one saved Marimo notebook into named web views. The
notebook owns data, Python computation, controls, and reusable results. Each
view owns the layout, wording, visual encoding, and browser interaction for one
job.

<StudioExample family="occupancy" />

The Building occupancy notebook supports a live monitor and a model review.
Both views use the same sensor analysis. Each has its own source documents,
browser dependencies, build, route, and current artifact.

## The product model

```text
saved Marimo notebook
  -> named view
  -> view project
  -> built artifact
  -> Preview with notebook results
```

A **view** is the stable name and URL, such as `monitor` or `model-review`. Its
**view project** is the saved frontend directory. A **view provider** inspects
that project and builds an immutable browser **artifact**. Studio combines the
artifact with a notebook runtime to create the **presentation** shown in
Preview.

The notebook and each view can change independently:

| Action                 | Result                                                           |
| ---------------------- | ---------------------------------------------------------------- |
| Save notebook code     | Marimo reruns affected cells and updates mounted results         |
| Save a source document | Studio builds a new artifact for the selected view               |
| Switch views           | Studio presents another artifact against the same notebook       |
| Switch runtimes        | The same artifact receives results from another notebook runtime |

A failed build keeps the last successful artifact available while Source shows
the diagnostic.

## Notebook results enter the view by name

View source can place a complete cell, render one Python object, or read a
browser value:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

Studio resolves each target to the notebook cell that produces it and the
upstream cells required to compute it. Marimo keeps control changes and
dependent results reactive while the frontend stays mounted.

[Place notebook results in a view](guide/notebook-results.md) explains the
three projection forms.

## Studio connects three authoring surfaces

- **Notebook** edits Python and reactive computation.
- **Source** edits the selected view project's source documents.
- **Preview** renders the current artifact with live notebook results.

The Develop layout shows all three. Saved layouts and compact navigation let
you arrange them for a larger or narrower workspace.

[Create your first view](guide/getting-started.md) for a working path from a
saved notebook. [Why Studio?](why-studio.md) explains the product decision
behind the model.
