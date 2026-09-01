---
title: Why Studio?
description: Keep one reproducible analysis and build the right frontend for each purpose.
---

# Why Studio?

Agentic coding makes creating user interfaces inexpensive.

A coding agent can turn a dataset into a dashboard, report, or bespoke web
application quickly. The costly part is the analysis behind it: deciding
which data to trust, how measures are defined, which transformations are valid,
what assumptions apply, and which results can support a decision.

That work accumulates over time. It reflects human attention, domain knowledge,
experiments, corrections, and judgment. A reproducible notebook captures this
work as an executable program.

The need for an interface can change much faster. The same person may need an
explorer while investigating a question, a monitor while tracking a process,
and a presentation while explaining a result.

**Keep the analysis. Build the right interface for each job.**

Many systems turn code and data into interactive experiences. Reactive
application frameworks like [Streamlit](https://github.com/streamlit/streamlit),
[Shiny](https://github.com/rstudio/shiny),
[Gradio](https://github.com/gradio-app/gradio), and
[Reflex](https://github.com/reflex-dev/reflex) make an application and its
runtime the main artifact. Publishing systems like
[Quarto](https://github.com/quarto-dev/quarto-cli) and
[Observable Framework](https://github.com/observablehq/framework) render
documents and sites from code, data, and browser assets. Notebook systems like
[Observable Notebook Kit](https://github.com/observablehq/notebook-kit) make the
notebook itself runnable, embeddable, and publishable. Bespoke web applications
define their own connections to data and computation.

Studio is built around a different relationship. One reproducible marimo
notebook holds the analysis. Independent views turn selected notebook results
into interfaces for different purposes.

## Preserve the analysis

A [marimo](https://github.com/marimo-team/marimo) notebook is stored as pure
Python. Its dependency graph determines execution order from the variables each
cell defines and reads. Running a cell updates its dependents, while deleting a
cell removes its variables from program memory. Code, outputs, and program state
remain synchronized.

Marimo notebooks are Git-friendly, executable as scripts, and testable with
standard Python tools. Package requirements can travel with the notebook. The
notebook is both an interactive workspace and a reproducible software artifact.

Over time, it records more than code. It captures the questions an analyst
asked, the sources selected, the transformations accepted, the measures
defined, the assumptions exposed, the checks performed, and the corrections
retained.

The notebook captures human attention and analytical decisions as executable
Python.

Studio keeps that notebook behind every view. A new interface starts from the
same saved definitions, dependency graph, and reactive computation. The
analysis remains inspectable, testable, and reusable as the ways of working
with it change.

## One notebook, many purposes

One analysis may need to support exploration, monitoring, review, explanation,
or presentation. These use cases can share the same definitions while requiring
different visual encodings, interactions, and browser libraries.

```text
reproducible notebook
  ├── explorer
  ├── monitor
  ├── review
  ├── report
  └── presentation
```

Each view is its own [frontend project](guide/frontend-options.md) with its own
source files, browser dependencies, build, route, and last successful artifact.

A shared analytical change belongs to the notebook. A change made for one use
case belongs to its view. Correcting a measure can update every view that
consumes it. Changing a visual encoding, interaction, or explanation affects
the view that owns it.

This separation also applies when one person uses several views. The same
analyst can move from open-ended exploration to a focused review. The same
operator can use a live monitor during an incident and a report afterward. Each
situation can have an interface designed for the task while the underlying
analysis stays the same.

Modern frontend code remains modern frontend code. A view can begin with HTML
plus inline or local CSS and JavaScript. It can also use React, Svelte, an
existing frontend build, and specialized visualization libraries. Each choice
can use its normal package tooling, browser APIs, graphics systems, and
interaction techniques.

## Separate Python and frontend

Studio views are frontend projects, not Python templates.

View source contains no Python execution surface. All Python computation that
produces notebook results runs in the notebook runtime. Studio does not evaluate
Python expressions inside HTML, CSS, or JavaScript, and it does not add a
Jinja-style interpolation layer to view source.

The notebook owns data access, transformations, metrics, models, reusable
controls, and Python execution. The view owns layout, visual encoding, wording,
and browser interaction.

A view may perform local browser operations such as formatting, brushing,
filtering, navigation, or camera movement. Shared analytical definitions and
Python computation remain in the notebook.

Views [reference the notebook results they
need](guide/notebook-results.md) by name:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

A complete cell preserves its controls, output, logs, errors, and reactive
behavior. A rendered output retains marimo's native renderer. A browser value
provides JSON-compatible data or an Arrow-backed dataframe to frontend code.

Stable names form the connection between the two sides. Studio resolves each
name to its notebook producer and upstream dependencies. When a control changes,
marimo reruns the affected Python computation and Studio updates the mounted
result. The frontend remains mounted throughout the update.

Notebook code contains the analytical program. View source contains the
interface. Python computation stays in the notebook, while view-specific
layout, styling, browser dependencies, and wording stay in the view.

## Trust every iteration

An agent can generate or rewrite frontend source quickly. That speed increases
the need to know which source was changed, which notebook result it used, which
build is visible, and which rendered view was actually checked.

Studio gives those operations explicit revisions. A source read returns its
current revision. A write commits against that revision. If a person or another
agent saved first, Studio preserves the newer source and reports the conflict.

A build uses a coherent source snapshot and publishes an immutable artifact. A
failed build reports source-located diagnostics and keeps the last successful
view available.

[Human and agent authoring](guide/coding-agents.md) follow the same visible
sequence:

```text
inspect → edit → build → show → verify
```

Browser evidence belongs to a specific notebook source, view, runtime, and
presentation revision. A rendered result remains traceable to both the
analytical program and the frontend artifact that produced it.

Studio lets interfaces change quickly while the work behind them remains
stable. One reproducible notebook preserves the analysis and the human
decisions accumulated within it. Independent views apply that analysis to
different purposes with ordinary frontend technology. Every published view
stays connected to the computation and revision behind it.
