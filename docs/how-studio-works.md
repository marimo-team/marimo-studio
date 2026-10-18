---
title: How Studio works
description: See what the notebook, the view project, the view provider, and the session each do when someone opens a view, and which data passes between them.
---

# How Studio works

Studio joins two things you write: a [notebook](reference/glossary.md#notebook)
and a [view project](reference/glossary.md#view-project). This page uses the
view `dashboard` of `analysis.py` to show what each part does and which data
passes between them.

<llm-exclude>

<StudioPipeline />

</llm-exclude>

<llm-only>

```text
studio/analysis/dashboard/   view project: your source
    │ build inputs
    ▼
view provider                build() and render()
    │ page files
    ▼
page                         HTML in the browser, with hosts
    ▲
    │ results by name
    │
session                      marimo runs analysis.py
```

</llm-only>

The page sits between two sources that change at different times. Saving view
source runs a build and publishes a new page. Changing a control reruns
notebook cells and sends new results to the page that is already open, with
no build. A Typst or LaTeX view adds a third path, in which the provider
compiles a new PDF from the new results.

## The notebook runs in a session

`analysis.py` is an ordinary marimo notebook. When someone opens the
dashboard, marimo runs the notebook in a
[session](reference/glossary.md#session) and keeps every cell's results. Three
of its cells, abridged:

```python
@app.cell
def region_control(mo):
    region = mo.ui.dropdown(
        ["North", "South"], value="North", label="Region"
    )
    region
    return (region,)


@app.cell
def quarterly_section(mo, orders, plot_quarters, region):
    quarterly_chart = plot_quarters(orders, region.value)
    mo.vstack([
        mo.md("### Orders per quarter"),
        quarterly_chart,
        mo.md("Source: order log"),
    ])
    return (quarterly_chart,)


@app.cell
def summary(orders, region):
    rows = orders[orders["region"] == region.value]
    summary = {"orders": len(rows)}
    return (summary,)
```

The notebook holds every line of Python the dashboard depends on. Studio reads
results from the session and leaves the cells as they are.

## The view project holds the presentation

The dashboard's files live in their own folder beside the notebook:

```text
analysis.py
studio/analysis/
  dashboard/
    view.toml     names the provider that builds the view
    index.html    the page source
    AGENTS.md     conventions for coding agents
```

The view project is an ordinary project in its
[format](reference/glossary.md#format), here a plain HTML page. `index.html`
lays out the page and names the notebook results it shows:

```html
<main id="app-shell">
  <h1>Regional orders</h1>
  <marimo-cell name="region_control"></marimo-cell>
  <marimo-output value="quarterly_chart"></marimo-output>
  <p>Orders: <strong mo-value="summary.orders"></strong></p>
</main>
```

`<marimo-cell>`, `<marimo-output>`, and the `mo-value` attribute are
[hosts](reference/glossary.md#host): elements that mark where a notebook
result goes. They belong to the page. The notebook never contains them.

Edit the view project in Studio's Source pane, in your own editor, or with a
coding agent. Studio watches the folder and builds again when you save a build
input, such as `index.html`. A
second view, such as a Typst `report`, gets its own folder beside
`dashboard/`.

## A view provider builds the page

`view.toml` names the [view provider](reference/glossary.md#view-provider):

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

A view provider is Python code that knows one format. For each
[build](reference/glossary.md#build), it receives a copy of the view project's
[build inputs](reference/glossary.md#build-input) and writes a
[page](reference/glossary.md#page): an HTML entry
file and the files it loads. The HTML provider copies the page. The React
provider bundles the app with Vite. The Typst provider prepares a document to
compile.

A build never runs the notebook, so the page it writes holds empty hosts. A
failed build leaves the last good page in Preview and shows the error beside
the source.

## Hosts receive results while the page is open

When the page opens, Studio connects it to the session. For each host, Studio
resolves the name to the cell that computes it, runs that cell and the cells
it depends on, and sends the result to the host. Pick a region in either pane
of this figure, or point at a host to find its cell:

<llm-exclude>

<StudioResultMap />

</llm-exclude>

| Host                                      | The page receives                                                                                                                             |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `<marimo-cell name="region_control">`     | The cell as marimo renders it, with its live dropdown                                                                                         |
| `<marimo-output value="quarterly_chart">` | The rich representation of the variable `quarterly_chart` alone, here a figure, or an image of it when the host sets `accept`                 |
| `mo-value="summary.orders"`               | The value as JSON. Text, a number, or a boolean appears in the element as text, and page code reads any value from its `marimoValue` property |

A host for an output names a variable, so it can take one piece of what a cell
shows. `quarterly_section` shows a stack with a heading, the chart, and a
caption. `<marimo-output value="quarterly_chart">` places only the chart, while
`<marimo-cell name="quarterly_section">` would place the whole stack.

A dataframe reaches page code as a [Flechette](https://github.com/uwdata/flechette)
`Table`, which Studio decodes from Arrow IPC. Python objects stay in the
session.

When a reader picks **South**, the browser sends the dropdown's new value to
the session. marimo reruns `quarterly_section` and `summary`, the cells that
read it, and Studio sends their new results to the hosts that show them. Each
view reads its results from the notebook, so every view agrees with it.
[Place notebook results in a view](guide/notebook-results.md) covers each kind
of host.

## Renders turn results into files

A PDF holds no live elements, so a Typst or LaTeX view reads results while it
compiles:

```typst
#import "marimo.typ": marimo_output, marimo_value

The #marimo_value("region.value", default: "selected") region placed
#marimo_value("summary.orders", default: 0) orders.

#marimo_output("quarterly_chart", width: 100%)
```

The provider declares this file as a [render](reference/glossary.md#render).
When a result the render reads changes, Studio calls the provider with values
in their JSON form and outputs as media such as images, and the provider
compiles a new PDF
with its own tool. The view's page shows the PDF with a download link.

The provider also reports where each result landed in the PDF, as
[render regions](reference/glossary.md#render-region). Studio uses them to
trace a figure or a table cell inside the PDF back to the cell that computed
it, as [Select results with Lens](guide/lens.md) shows.

## Where the session runs

The [runtime](reference/glossary.md#runtime) decides where the notebook's
Python runs. The view project stays the same for each:

| Runtime      | The session runs                                        |
| ------------ | ------------------------------------------------------- |
| **Python**   | On a server, through `marimo edit` or `marimo run`      |
| **Browser**  | In each visitor's browser, through Pyodide              |
| **Prepared** | On your machine, during export, once per prepared state |

A prepared export runs no Python while visitors read it. Studio saved each
prepared state's results during export, and the page moves between them.
[Run or export a view](guide/run-and-share.md) compares the runtimes.

## Next steps

- [Getting started](guide/getting-started.md) builds a first view by hand.
- [Choose a format](guide/formats.md) compares the built-in formats.
- [Select results with Lens](guide/lens.md) traces any part of a view back to
  its cell.
- [Add a view provider](guide/view-providers.md) connects another framework or
  tool.
- The [glossary](reference/glossary.md) defines every term on this page.
