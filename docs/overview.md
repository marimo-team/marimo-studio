---
title: Overview
description: How Marimo Studio turns one reactive notebook into several authored web views.
---

# Overview

Marimo Studio adds authored web documents inside a Marimo process. The notebook
owns data, transformations, calculations, reactive state, and domain logic.
Each view selects notebook results and arranges them for one audience or task.

## Keep analysis in notebook cells and frontend code in view files

Marimo's reactive notebook editor is the home for data access,
transformations, metric definitions, assumptions, and domain decisions.
Notebook cells keep this context executable, inspectable, and connected through
reactive dependencies.

A Studio view is the home for page structure, CSS, JavaScript, assets, and
browser interactions. People and coding agents edit these ordinary web files
while every projection remains connected to notebook state. An analyst can
improve a definition once, inspect the supporting cells, then review its effect
in every view that uses the result.

## Studio runs inside Marimo

Marimo owns the editor, process, notebook execution, reactive graph, sessions,
authentication, routing, controls, and output renderers. Studio registers its
workspace, authored documents, projections, and presentation routes through
Marimo's extension points.

Run the configured notebook with `marimo edit` to work on the notebook and
view together. Run it with `marimo run` to serve the finished views.

::: tip Choose the presentation surface
Use Marimo's native notebook and application layouts when their reading order
and controls fit the audience. Add a Studio view when the audience needs a
separately authored web document, standard browser behavior, or another page
backed by the same notebook.
:::

<ol class="studio-runtime-flow" aria-label="From notebook to reactive view">
  <li>
    <strong>Write the notebook</strong>
    <span>Marimo cells load data, compute results, and create controls or outputs.</span>
  </li>
  <li>
    <strong>Create a view</strong>
    <span>Studio adds a web document beside the notebook and opens a live preview.</span>
  </li>
  <li>
    <strong>Project results</strong>
    <span>The document places complete cells, rich Python objects, or JSON-compatible values.</span>
  </li>
  <li>
    <strong>Marimo reacts</strong>
    <span>Control changes rerun dependent cells and update every affected projection.</span>
  </li>
</ol>

## One notebook, several views

Each view is an ordinary directory of authored web files:

```text
analysis.py
__marimo__/
  studio/
    analysis/
      dashboard/
        index.html
        app.css
        app.js
      executive/
        index.html
        app.css
```

Both documents can use the same notebook definitions. A dashboard might keep
controls and a detailed table visible. An executive view can project the same
forecast into a concise summary.

| Notebook owns                                        | View owns                        |
| ---------------------------------------------------- | -------------------------------- |
| Data access, transformations, and metric definitions | Reading order and page structure |
| Calculations and reactive dependencies               | Audience-specific wording        |
| Controls and widget models                           | HTML, CSS, modules, and assets   |
| Plots, tables, downloads, and other outputs          | Which notebook results appear    |

Changing one notebook definition updates each view that projects its result.
Changing one view leaves the notebook and other views unchanged.

## Project notebook results

Views use three projection forms:

```html
<marimo-cell name="analysis"></marimo-cell>
<marimo-output value="revenue_table"></marimo-output>
<strong mo-value="report.total"></strong>
```

`<marimo-cell>` mounts the complete output of a named cell or configured
alias. Marimo's output plugins keep controls, plots, tables, downloads, and
anywidgets interactive.

`<marimo-output>` selects one Python object and asks Marimo to format it as
native output. Use it to place a DataFrame, plot, Markdown object, control, or
widget independently from the defining cell's complete output.

`mo-value` reads a JSON-compatible Python value and renders it as text or
compact JSON. A browser module can also read the typed snapshot through the
host's `marimoValue` property.

[Use notebook results](guide/notebook-results.md) develops all three patterns.
The [view document reference](reference/view-document.md) defines selectors,
states, events, and loading behavior.

## Author with standard web files

Each view is a complete HTML document. Relative stylesheets, JavaScript
modules, images, fonts, imports, and CSS `url(...)` references resolve from the
authored files. Browser APIs, SVG, Canvas, Web Components, and existing
libraries run through the regular browser lifecycle.

CSS saves update the current stylesheet. HTML saves replace the authored
`#app-shell` around the mounted Marimo runtime. A module change reloads the
view document so the browser evaluates its module graph again.

## Work with coding agents

The `marimo_studio.agents` module exposes a bounded view-authoring workflow. An
agent can inspect the saved notebook graph, create a named view, bind a stable
cell reference, edit ordinary web files, and validate the resulting
projections. Transformations, metric definitions, and domain rules remain in
notebook cells where a person can inspect and run them.

[Work with coding agents](guide/coding-agents.md) develops the complete
inspect, create, edit, and check loop.

## Choose where the notebook runs

Studio provides two presentation runtimes:

| Runtime     | Notebook execution                    | Use it for                                                                              |
| ----------- | ------------------------------------- | --------------------------------------------------------------------------------------- |
| Server      | A Python kernel in the Marimo process | Python packages, local resources, databases, credentials, and server deployment         |
| WebAssembly | A Pyodide worker in the browser       | Browser previews and static exports whose dependencies and data sources work in Pyodide |

In edit mode, the Server preview joins the editor's Python session. Native
controls and anywidget models operate against the same kernel.

The WebAssembly preview runs another notebook instance. Studio synchronizes
JSON-compatible values from matching native Marimo controls, then each kernel
reruns its own reactive graph. Anywidget state remains with the runtime that
created its model.

Control identity uses the control's cell and its position inside that cell.
Construct the same native controls in the same order in both runtimes when a
view needs cross-runtime synchronization. Values that are not JSON-compatible
remain in their originating runtime.

In run mode, each browser receives its own server kernel or WebAssembly worker.
[Run, export, and share](guide/run-and-share.md) covers deployment, static
export, and the runtime boundaries that affect credentials and data access.

Start with [Create your first view](guide/getting-started.md), or inspect the
[examples](examples/) to compare a compact dashboard with a three-stage
research workflow.
