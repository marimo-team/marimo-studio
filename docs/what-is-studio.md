---
title: What is Studio?
description: Keep one reactive analysis behind views built for different audiences and tasks.
sidebar: false
aside: false
pageClass: studio-overview-page
next:
  text: Guide overview
  link: /guide/
---

# What is Studio?

Studio turns one reactive [marimo](https://marimo.io/) notebook into named
views: web apps, slide decks, articles, and PDF reports. Keep your data,
calculations, controls, and assumptions in Python. Give each audience a view
designed for the work they need to do.

<StudioViewStack family="quadratic-programs" />

The Quadratic programs notebook backs a Reveal.js lecture, an HTML explainer, a
Svelte lab, and a Typst PDF report. Each view presents the same solution through
its own layout, interaction, and explanation.

## Notebook and views

A notebook preserves the decisions behind the result: where data comes from,
how a measure is defined, which assumptions a model uses, and how corrections
are applied. marimo tracks dependencies and reruns affected cells as inputs
change.

A view gives those results a purpose. An analyst may need a detailed explorer,
a decision-maker a brief report, and a class an interactive explanation. Each
view has its own source and URL while drawing on the same notebook.

## Notebook results as building blocks

A key idea is that a view places notebook results by name. A result is a
complete _cell_ with its controls, a rendered _output_ such as a chart, or a
_value_ such as a number or a record. Studio resolves each name to the cell
that computes it, so every result a view shows traces back to the notebook.

::: v-pre

| Result | Web page                         | Quarto                                | Typst                           | LaTeX                        |
| ------ | -------------------------------- | ------------------------------------- | ------------------------------- | ---------------------------- |
| Cell   | `<marimo-cell name="filters">`   | `{{< marimo cell="filters" >}}`       | `#marimo_cell("filters")`       | `\marimocell{filters}`       |
| Output | `<marimo-output value="chart">`  | `{{< marimo output="chart" >}}`       | `#marimo_output("chart")`       | `\marimographics{chart}`     |
| Value  | `<span mo-value="totals.rooms">` | `{{< marimo value="totals.rooms" >}}` | `#marimo_value("totals.rooms")` | `\marimovalue{totals.rooms}` |

:::

A view is a page or a rendered document. A _page_ is HTML that the browser
keeps live. HTML, React, Svelte, Notebook Kit, and
[Quarto](https://quarto.org/) views are pages, so moving a control reruns the
affected cells and updates every result on the page. A _rendered document_ is a
file that Studio renders from the notebook's values and outputs. A
[Typst](https://typst.app/) or [LaTeX](https://www.latex-project.org/) view
compiles a PDF. In the editor and in
Python-runtime apps, Studio compiles it again when a result it reads changes.
[Rendered documents](reference/projections.md#rendered-documents) lists what
each runtime and export shows. A PDF holds no controls, so a Typst or LaTeX
document places values, outputs with an image form, such as figures and
charts, and the images that cells show.

In the [Quadratic programs](examples/quadratic-programs.md) views at the top
of this page, **Lecture**, **Explainer**, and **Lab** are pages, and **Report**
is a Typst PDF that embeds the matplotlib figures the notebook draws.
[Place notebook results in a view](guide/notebook-results.md) develops
each result, and [Choose a frontend](guide/frontend-options.md) compares the
formats.

## Product model

A **view** is a name and URL, such as `monitor` or `report`. Its **view project**
is the saved source directory. A **view provider** builds that project into an
immutable **artifact**. Studio combines the artifact with a notebook runtime to
create the **presentation** shown in Preview.

| Action                      | Result                                               |
| --------------------------- | ---------------------------------------------------- |
| Run changed notebook code   | marimo updates dependent results in the view         |
| Save a view Source document | Studio builds and publishes the updated view         |
| Switch views                | The next view uses the same live notebook session    |
| Change runtime              | The same artifact receives results from that runtime |

A failed build keeps the last successful artifact available while Source shows
the diagnostic. Each view can evolve independently.

## Notebook, Source, and Preview

Studio brings **Notebook**, **Source**, and **Preview** together. Edit Python,
shape the view, and inspect the result side by side. The native agent sidebar
remains available throughout.

Follow [Getting started](guide/getting-started.md), browse the
[examples](examples/index.md), [author with a coding
agent](guide/coding-agents.md), or choose a [runtime](guide/run-and-share.md)
for a live application, browser execution, or a prepared static report.
