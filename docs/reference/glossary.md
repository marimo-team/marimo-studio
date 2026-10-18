---
title: Glossary
description: Definitions of the terms the Studio documentation uses, from notebooks and results to views, providers, builds, and runtimes.
---

# Glossary

Every term on this page keeps one meaning across the Studio documentation.
Where another page links a term, hovering over the link or focusing it shows
the definition. [How Studio works](../how-studio-works.md) connects the terms
in one walkthrough.

## The notebook

### Notebook {#notebook}

The [marimo](https://marimo.io/) Python file, such as `analysis.py`, that a
view presents. It holds the data, the computation, and the controls, and all of
a view's Python lives in it.

marimo runs a notebook reactively. When a cell's inputs change, marimo reruns
that cell and every cell that reads what it defines.
[What is Studio?](../what-is-studio.md#python-in-the-notebook-presentation-in-the-view)
explains how a notebook and its views divide the work.

### Cell {#cell}

One function in the notebook, named by its function name. Placed in a view, a
cell shows everything the notebook shows for it: its output, its controls, its
errors, and its console output when the notebook shows cell logs.

### Control {#control}

An interactive element that a cell creates with `mo.ui`, such as a slider or a
dropdown. Changing a control reruns the cells that read its value.

### Session {#session}

A running copy of the notebook. marimo runs the notebook's cells in a session
and keeps their results, and a page reads those results by name.

The [runtime](#runtime) decides where the session runs. `marimo run` starts a
session for each visitor, so one visitor's controls leave another visitor's
results unchanged.

## Results

### Result {#result}

Something the notebook computes that a view can place: a [cell](#cell), an
[output](#output), or a [value](#value). A view names each result, and Studio
resolves the name to the cell that computes it.

### Output {#output}

One Python object from the notebook, such as a chart, shown the way marimo
renders it. A view names the variable that holds the object, so the notebook
need not display it.

### Value {#value}

Notebook data, such as a number, a record, or a table, that a view formats or
draws itself. A page receives it as JSON, or a dataframe as an Arrow table. A
render receives its JSON form.

### Value selector {#value-selector}

A variable name with optional steps into the object it holds, such as
`summary.total`, `rows[0]`, or `results["overview"]`. Outputs and values are
named by value selectors.

### Target {#target}

The name a view uses for one result: a cell name or [cell alias](#cell-alias)
for a cell, and a [value selector](#value-selector) for an output or a value.

### Cell alias {#cell-alias}

A name that Studio stores in the notebook's `[tool.marimo-studio.cells]` table
for a cell whose function has no name. Views place the cell by its alias.

## Views

### View {#view}

One named presentation of a notebook for one audience, such as a slide deck
named `lecture` or a PDF named `report`. A notebook has one or more views, and
each view has its own [view project](#view-project) and URL, such as
`/lecture/`.

The default view opens at `/`.
[Work in Studio](../guide/work-in-studio.md#manage-views) creates, switches,
renames, and removes views.

### View project {#view-project}

The folder that holds one view's source, such as `studio/analysis/dashboard/`.
It is an ordinary project in the view's [format](#format), such as an HTML
page, a React app, or a Typst document, so any editor, tool, or coding agent
can change it.

Studio watches the folder and rebuilds the view when a
[build input](#build-input) changes. Every view project holds a
[`view.toml`](#view-toml).

### Views folder {#views-folder}

The folder beside the notebook that holds its view projects, such as
`studio/analysis/` for `analysis.py`. Commit it with the notebook.

### `view.toml` {#view-toml}

The file in every view project that names the
[view provider](#view-provider) that builds the project, and the options that
provider reads. Studio writes it when it creates the view.

### Format {#format}

The kind of project a view is, such as plain HTML, React, Svelte, Quarto,
Typst, or LaTeX. The view's [provider](#view-provider) builds that format.
[Choose a format](../guide/formats.md) compares the built-in formats.

### Starter {#starter}

A template that writes the first files of a new view project. Choose one in
the **New view** form, or pass `--starter` to `marimo-studio view create`.

### View provider {#view-provider}

A Python package that teaches Studio one [format](#format). It offers
starters, reports which files of a view project people edit and which files
the build reads, locates the hosts in those files, and builds the project into
a [page](#page).

Studio ships providers for HTML, React, Svelte, Observable Notebook Kit,
Quarto, Typst, and LaTeX.
[Add a view provider](../guide/view-providers.md) writes one for another
framework or tool.

### Provider key {#provider-key}

The name of an installed view provider, made from its Python distribution name
and its registration name, such as `marimo-studio/react`. `view.toml` stores
it.

## Pages and hosts

### Page {#page}

The HTML that a view's [build](#build) produces. Every view reaches its readers
as a page in the browser, and Studio fills the page's [hosts](#host) with
notebook results.

A Typst or LaTeX view's page shows its [render](#render), the PDF, with a
download link.

### Host {#host}

An element in a page that names one [result](#result): `<marimo-cell>` for a
cell, `<marimo-output>` for an output, or any element with an `mo-value`
attribute for a value. Studio fills each host with its result and updates it
when the result changes.

`<marimo-cell>` and `<marimo-output>` are
[custom elements](https://developer.mozilla.org/en-US/docs/Web/API/Web_components/Using_custom_elements),
HTML elements that a page defines for itself. Studio defines both in every page
it publishes. Quarto's `marimo` shortcode writes hosts for a Quarto view.

### App shell {#app-shell}

The one element with `id="app-shell"` that holds a page's own content. Studio
refreshes it in place when a new build publishes, and Lens selections work
inside it. Place hosts inside it.

### Projection {#projection}

The connection Studio keeps between one host and its result while the page is
open. Studio resolves the host's target to the cell that computes it, runs that
cell and the cells it depends on in the session, and mounts the result in the
host.

### Render {#render}

A file, such as a PDF, an image, or a video, that a provider makes from
notebook results with its own tool. Typst and LaTeX views render a PDF. Studio
renders the file again when a result it reads changes, and the view's page
shows the file.

## Building and editing

### Build {#build}

The step in which the view's provider turns the view project into a page.
Studio builds when a build input changes. A notebook rerun needs no build,
because the page receives new results while it runs.

### Build input {#build-input}

A file of the view project that the build reads. Saving a build input
rebuilds the view.

A file can be a [source document](#source-document), a build input, or both.
A React view shows its lockfile in Source as read-only, and the lockfile still
affects the build. Editing `DESIGN.md` leaves the build unchanged.

### Source document {#source-document}

A file of the view project that the [Source](#source) pane shows, editable or
read-only. The view's provider chooses these files, and Studio adds
`view.toml`.

### Source {#source}

The Studio pane that edits the view's source documents. It opens beneath
Preview from **Edit view source**.

### Preview {#preview}

The Studio pane that shows the view's latest successful build, running against
the live notebook. When a build fails, Preview keeps the previous page.

### Artifact {#artifact}

The validated, unchangeable set of files that one successful build produces.
Studio publishes each artifact as a new revision, and a failed build leaves the
current artifact in place.

### Presentation {#presentation}

One artifact combined with the notebook, its runtime configuration, its
projections, and the browser session that shows them.
[Identities and state](identities.md) defines the revisions that identify a
presentation.

## Running and sharing

### Runtime {#runtime}

Where the notebook's Python runs when someone opens a view. Studio has three:
the [Python runtime](#python-runtime), the
[Browser runtime](#browser-runtime), and the
[Prepared runtime](#prepared-runtime).

[Run or export a view](../guide/run-and-share.md) compares them.

### Python runtime {#python-runtime}

The notebook runs in a marimo session on a server, through `marimo edit` or
`marimo run`. Its configuration ID is `server`. It can read private files,
credentials, native packages, and services.

### Browser runtime {#browser-runtime}

The notebook runs in each visitor's browser, in a worker, through
[Pyodide](https://pyodide.org/), a build of Python for
[WebAssembly](https://webassembly.org/). Its configuration ID is `wasm`.
Visitors receive the notebook source.

### Prepared runtime {#prepared-runtime}

The notebook ran ahead of time, during export, once for each
[prepared state](#prepared-state), and the page shows the saved results.
Visitors run no Python and receive no notebook source. Its runtime ID is
`zero-python`.

### Prepared export {#prepared-export}

A static site that `marimo-studio view export` writes for the Prepared
runtime. It holds the built page and the saved results, and any static host,
such as GitHub Pages, can serve it.

### Prepared state {#prepared-state}

One combination of control values that a prepared export computes ahead of
time. `states.yaml` in the view project lists them. Changing a control in a
prepared export moves the page to another saved state.

## Selecting with Lens

### Lens {#lens}

A marimo widget, from the [marimo-lens](https://marimo-team.github.io/marimo-lens/)
package, that lets you select part of a rendered result, add a note, and hand
both to a coding agent with the notebook code behind it. In Studio, Lens
selects parts of views as well as notebook outputs.

### Selection {#selection}

One thing you pointed at with Lens: a target, the point or area you marked on
it, and your note. Lens labels selections `S1`, `S2`, and so on, and an agent
reads each one with the notebook cells behind it.

### Lens target {#lens-target}

A part of a view that Lens can select: a host, a region that page code draws
from declared inputs, an authored region of the page, or a
[render region](#render-region).

### Render region {#render-region}

A rectangle on a rendered file, such as a figure on a PDF page or a shape
during part of a video, with the notebook results it shows and the source line
that placed them. Lens selects render regions and traces them to their cells.

## View provider API

These terms appear in the [View provider API](provider-api.md) and in
[Add a view provider](../guide/view-providers.md).

### Starter key {#starter-key}

A starter's name within its provider, such as `default` or `reveal`.

### Starter ID {#starter-id}

A provider key and a starter key joined by a colon, such as
`marimo-studio/react:reveal`. `--starter` takes a starter ID.

### Provider options {#provider-options}

The `[options]` table in `view.toml`. A provider declares the options it reads,
and Studio rejects any other option.

### Cell target {#cell-target}

The name that a `<marimo-cell>` host in a new view uses: a marimo cell name, or
a cell alias that Studio proposes for a cell without one.

### Projection site {#projection-site}

The location, kind, and targets of one host in a view project's source. A
provider reports one site per host, so Studio can connect each host in the
built page to the notebook.

### Build snapshot {#build-snapshot}

A private copy of the build inputs that a build reads, with a site ID marked
on every host. The view project on disk keeps its original markup.

### Render template {#render-template}

The private build output that each render starts from. A build writes it to
`BuildRequest.template_root`.

### Render value {#render-value}

A notebook value that a render reads in its JSON form.

### Render output {#render-output}

A notebook value, such as a figure, that a render places as an image.

### Render cell {#render-cell}

A named notebook cell whose output a render places as an image.

### Rendered files {#rendered-files}

The files that one render returns, with a main file and an optional preview.

### Render host {#render-host}

`<marimo-output render="main.typ">`, the host that shows a render's files on
the page.

### Accept list {#accept-list}

The media types that a host or a render can show for a result, in order of
preference.

### Diagnostic {#diagnostic}

A problem in a view project, with a code, a message, a hint, and an optional
source location. Source shows diagnostics beside the file they point at.
