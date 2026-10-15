---
title: What is Studio?
description: Studio builds web pages and typeset documents from the cells, outputs, and values of one marimo notebook.
sidebar: false
aside: false
pageClass: studio-overview-page
next:
  text: Getting started
  link: /guide/getting-started
---

# What is Studio?

marimo-studio builds views of a [marimo](https://marimo.io/) notebook. A view
is a web page, a slide deck, or a typeset document that places the notebook's
results by name. The notebook keeps the data, the computation, and the
controls. Each view keeps its own source and decides the layout, the wording,
and the format for one audience.

<StudioViewStack family="quadratic-programs" />

`quadratic_program.py` above backs four views. **Lecture** is a React and
Reveal.js deck, **Explainer** is a plain HTML page, **Lab** is a Svelte app,
and **Report** is a PDF typeset with [Typst](https://typst.app/). Choose
**Notebook** to see the analysis they all read from.

## Notebook results are building blocks

A view can place three kinds of notebook result:

- a **cell**, with its output and any controls it shows
- an **output**, one Python object rendered the way marimo renders it
- a **value**, such as a number, a record, or a table, for the view to format

Here are three cells from `quadratic_program.py`, abridged. The first shows a
slider, the second solves the optimization problem, and the third draws it:

```python
@app.cell
def pull_direction(mo):
    pull_direction = mo.ui.slider(0, 330, step=30, label="Direction of $q$")
    pull_direction
    return (pull_direction,)


@app.cell
def solution(q, solve):
    solution = solve(q)
    return (solution,)


@app.cell
def level_curves(bowl, draw_problem, region, solution):
    problem_figure = draw_problem(region, bowl, solution)
    problem_figure
    return (problem_figure,)
```

Each view format names the same results in its own syntax:

::: code-group

```html [HTML]
<marimo-cell name="pull_direction"></marimo-cell>
<marimo-output value="problem_figure"></marimo-output>
<p>The optimal value is <strong mo-value="solution.value"></strong>.</p>
```

```markdown [Quarto]
{{< marimo cell="pull_direction" >}}

{{< marimo output="problem_figure" >}}

The optimal value is {{< marimo value="solution.value" >}}.
```

```typst [Typst]
#import "marimo.typ": marimo_output, marimo_value

#marimo_output("problem_figure", width: 100%)

The optimal value is #marimo_value("solution.value", default: 0)
with $q$ pointing at #marimo_value("pull_direction.value", default: 0) degrees.
```

```latex [LaTeX]
\usepackage{marimo}

\marimographics[width=\linewidth]{problem_figure}

The optimal value is \marimonum{solution.value}
with $q$ pointing at \marimovalue{pull_direction.value} degrees.
```

:::

Studio renders the HTML and Typst sources into a live page and a PDF:

<StudioFigure
  name="cell-output-value"
  alt="The three notebook cells in marimo beside the HTML page and the Typst PDF. The page shows the live slider at 210 degrees, the level curves, and the optimal value. The PDF shows the same level curves and states the optimal value with q pointing at 210 degrees."
/>

What's going on here:

- `pull_direction` names a cell. A page shows the live slider. Moving it makes
  marimo rerun the cells that depend on it, and every result on the page
  updates. A PDF cannot hold a slider, so the Typst and LaTeX documents read
  its current value instead.
- `problem_figure` names an output, a matplotlib figure. A page renders it the
  way the notebook does. Typst and LaTeX draw it as a vector graphic at the
  width where the document places it, so its labels keep their point size.
- `solution.value` names a value. A page writes it into the element. A
  document reads it as JSON and formats it itself.

Studio resolves every name to the cell that computes it. A reader who doubts a
number on the page can follow it to that cell and through marimo's
[dataflow graph](https://docs.marimo.io/guides/editor_features/dataflow/) to the data behind
it, and `marimo-studio validate` reports each name a view declares that the
notebook no longer defines.

## Pages and documents

A **page** is HTML that stays live in the browser. The HTML, React, Svelte,
Reveal.js, Observable Notebook Kit, and [Quarto](https://quarto.org/) starters
create pages. Controls work, and results update as soon as marimo recomputes
them.

A **document** is a file that Studio renders from the notebook's results.
[Typst](https://typst.app/) and [LaTeX](https://www.latex-project.org/) views
compile a PDF. In the editor and in apps served with Python, Studio compiles
the document again whenever a result it reads changes. A Prepared export
renders one PDF for each input state it prepares.

## Any framework or tool

[Choose a format](guide/formats.md) compares the built-in starters. Two
extension points cover other libraries and toolchains:

- Page code reads a value from its `mo-value` host and draws it with any
  JavaScript library the page loads. The examples draw notebook values with
  D3, Mosaic, Three.js, MapLibre, Observable Plot, and Recharts.
- A [view provider](guide/view-providers.md) is a Python package that adds
  starters for another framework, template, or build tool, such as a Lit or
  Preact app, a static site generator, or another typesetting tool. Its
  starters appear in **Add view**, and its views build, preview, and export
  like the built-in ones.

## Views live beside the notebook

Each view is an ordinary project in its own folder. Studio builds it with the
toolchain of its format: a Vite build for Svelte, the Typst compiler for a
Typst report. Its files sit next to the notebook, so you commit them together:

```text
quadratic_program.py
studio/quadratic_program/
  explainer/   index.html, view.toml
  lab/         a Svelte and Vite project
  lecture/     a React and Reveal.js project
  report/      main.typ, marimo.typ, view.toml
```

`view.toml` names the provider that builds the view. Studio keeps build output
in `__marimo__/studio/quadratic_program/`, which Git ignores.

Keeping views out of the notebook keeps the analysis readable. A font change
lands in a view, and a formula change lands in the notebook. A coding agent
can redesign a view for a new audience without editing the cells that compute
its results.

## Editing, running, and sharing

Studio adds a **Notebook**, **Source**, and **Preview** workspace to
`marimo edit`. Saving view source rebuilds Preview. A failed build keeps the
last good view on screen and shows the error beside the source.

![Notebook, Preview, and view source in Studio](/screenshots/studio-develop.png)

The same view runs three ways:

| Runtime      | Where Python runs                                      | Typical use                                          |
| ------------ | ------------------------------------------------------ | ---------------------------------------------------- |
| **Python**   | A server, through `marimo run`                         | Private data, credentials, and native packages       |
| **Browser**  | Each visitor's browser, through Pyodide                | A static site where visitors compute new states      |
| **Prepared** | Your machine, once, during `marimo-studio view export` | A static site that keeps the notebook source private |

Every example on this site is a Prepared export.

## Next steps

- [Getting started](guide/getting-started.md) builds a first view by hand.
- [Author with a coding agent](guide/coding-agents.md) asks an agent for one.
- [Examples](examples/index.md) shows four notebooks with four views each.
