---
title: Overview
description: How one Marimo notebook provides several focused views through live cell and value projections.
---

# Overview

A Marimo Studio view is a web document backed by a Marimo notebook. The
notebook owns computation and reactive state. The view chooses which results
to show and gives them an audience-specific page structure.

Run the configured notebook with `marimo edit` to work on the notebook and
view together. Run it with `marimo run` to serve the finished views.

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
    <span>The document places complete cell outputs or JSON-compatible Python values.</span>
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

| Notebook owns                               | View owns                        |
| ------------------------------------------- | -------------------------------- |
| Data access and calculations                | Reading order and page structure |
| Reactive dependencies                       | Audience-specific wording        |
| Controls and widget models                  | HTML, CSS, modules, and assets   |
| Plots, tables, downloads, and other outputs | Which notebook results appear    |

Changing one notebook definition updates each view that projects its result.
Changing one view leaves the notebook and other views unchanged.

## Project cells and values

Views use two projection elements:

```html
<marimo-cell name="revenue_table"></marimo-cell> <strong mo-value="report.total"></strong>
```

`<marimo-cell>` mounts the complete output of a named cell or configured
alias. Marimo's output plugins keep controls, plots, tables, downloads, and
anywidgets interactive.

`mo-value` reads a JSON-compatible Python value and renders it as text or
compact JSON. A browser module can also read the typed snapshot through the
host's `marimoValue` property.

[Design a view](design-views.md) develops both patterns. The
[view document reference](view-api.md) defines selectors, states, events, and
loading behavior.

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
[Run and share views](share-views.md) covers deployment, static export, and the
runtime boundaries that affect credentials and data access.

## Edit web files around a live runtime

Studio serves each view as a web directory. Relative stylesheets, modules,
images, fonts, JavaScript imports, and CSS `url(...)` references resolve from
their authored files.

CSS saves update the current stylesheet. HTML saves replace the authored
`#app-shell` around the mounted Marimo runtime. A module change reloads the
view document so the browser evaluates its module graph through the regular
page lifecycle.

Start with [Create your first view](getting-started.md), or inspect the
[included examples](examples.md) to compare a compact dashboard with a
three-stage research workflow.
