---
title: What is Studio?
description: Keep one reactive analysis behind web views built for different audiences and tasks.
---

# What is Studio?

Marimo Studio turns one reactive Marimo notebook into named web views. Keep
your data, calculations, controls, and assumptions in Python. Give each audience
a page designed for the work they need to do.

<StudioViewStack family="occupancy" />

The Building occupancy notebook supports a live monitor, a model review, and a
printable PDF report. Each view presents the same sensor analysis through its own
layout, interaction, and explanation.

## Notebook and views

A notebook preserves the decisions behind the result: where data comes from,
how a measure is defined, which assumptions a model uses, and how corrections
are applied. Marimo tracks dependencies and reruns affected cells as inputs
change.

A view gives those results a purpose. An analyst may need a detailed explorer,
a decision-maker a brief report, and a class an interactive explanation. Each
view has its own source and URL while drawing on the same notebook.

Coding agents can build and revise those interfaces from Studio's installed
instructions. You review the rendered result, refine the task, and retain
shared analytical decisions in the notebook. [Author with a coding
agent](guide/coding-agents.md) starts that workflow.

## Product model

A **view** is a name and URL, such as `monitor` or `report`. Its **view project**
is the saved frontend directory. A **view provider** builds that project into
an immutable browser **artifact**. Studio combines the artifact with a notebook
runtime to create the **presentation** shown in Preview.

| Action                      | Result                                               |
| --------------------------- | ---------------------------------------------------- |
| Run changed notebook code   | Marimo updates dependent results in the view         |
| Save a view source document | Studio builds and publishes the updated page         |
| Switch views                | The next view uses the same live notebook session    |
| Change delivery runtime     | The same artifact receives results from that runtime |

A failed build keeps the last successful artifact available while Source shows
the diagnostic. Each view can evolve independently.

## Place notebook results by name

Place a complete cell, render one Python object, or display a browser value:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

Studio resolves each name to its producing notebook cell and dependencies.
Marimo keeps controls and results reactive while the frontend stays mounted.
[Place notebook results in a view](guide/notebook-results.md) develops the three
projection forms.

## Notebook, Source, and Preview

Studio brings **Notebook**, **Source**, and **Preview** together. Edit Python,
shape the view, and inspect the result side by side. The native agent sidebar
remains available throughout.

[Create your first view](guide/getting-started.md), browse the
[examples](examples/index.md), or choose a [delivery runtime](guide/run-and-share.md)
for a live application, browser execution, or a prepared static report.
