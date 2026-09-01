---
title: Why Studio?
description: Keep one reproducible analysis behind several purpose-built frontends.
---

# Why Studio?

A dashboard, report, monitor, and presentation may need the same analysis with
different interfaces. Studio keeps that analysis in one reactive Marimo
notebook and gives each interface its own named view.

```text
reproducible notebook
  ├── explorer
  ├── monitor
  ├── review
  ├── report
  └── presentation
```

The notebook preserves data access, transformations, measures, controls, and
assumptions as executable Python. A view applies those results to one audience
and task through HTML, CSS, JavaScript, [React](https://react.dev/),
[Svelte](https://svelte.dev/), or another view provider.

## Keep analytical decisions in one place

A Marimo notebook is a Python program with a dependency graph. When a cell
changes, Marimo reruns the cells that depend on it. The saved file remains
Git-friendly, executable, and testable with Python tools.

That file can retain the work that is expensive to reconstruct:

- data sources and transformations
- metric and model definitions
- controls and exposed assumptions
- validation and correction steps
- reusable tables, charts, and values

Agentic workflows can produce new interfaces quickly, but trustworthy
analytical decisions still require human attention. As that attention becomes
the scarce input, one notebook preserves the sources, definitions, assumptions,
and corrections that every generated view depends on.

Correct a shared measure in the notebook and every view that consumes it can
receive the corrected result. Change a view's layout or explanation and the
other views keep their own source documents and artifacts.

## Give each job its own interface

The same analysis may support open-ended exploration, daily monitoring, model
review, and a concise briefing. Each job can use a different visual encoding,
interaction model, and browser library.

<StudioExample family="athletes" />

The Rio athletes notebook supports a publication report, a linked data
explorer, and a [Three.js](https://threejs.org/) briefing. The report mounts
Marimo controls and rendered output. The explorer uses
[Svelte](https://svelte.dev/), [Mosaic](https://uwdata.github.io/mosaic/), and
[DuckDB-WASM](https://duckdb.org/docs/stable/clients/wasm/overview), the browser
build of the DuckDB analytical database. The briefing places the same athlete
records in a navigable 3D presentation.

Each named view has its own view project, route, build, and last successful
artifact. The notebook remains the shared analytical source.

## Keep Python and frontend work legible

Python computation runs in the notebook runtime. View source owns browser
layout and interaction. It references notebook results through explicit hosts:

```html
<marimo-cell name="sport_control"></marimo-cell>
<marimo-output value="selected_roster"></marimo-output>
<span hidden mo-value="top_sports"></span>
```

This boundary keeps analytical definitions inspectable in Python and frontend
work recognizable to web developers. Browser code can format, filter, brush,
navigate, and render projected values. Shared analytical computation remains
in the notebook.

## Keep each iteration traceable

Studio reads and writes source documents against revisions. It builds from a
coherent source snapshot, validates the result, and publishes an immutable
artifact. A failed replacement leaves the preceding artifact in Preview.

People and coding agents use the same visible loop:

```text
inspect -> edit -> build -> show -> verify
```

Browser validation is tied to the active notebook, view, runtime, and
presentation. The rendered result stays connected to the analytical program
and frontend artifact that produced it.

Continue with [What is Studio?](what-is-studio.md) for the product nouns or
[Create your first view](guide/getting-started.md) to build one.
