---
title: One notebook, many views
description: One reactive notebook preserves analytical context while each view defines its own presentation and interaction.
---

# One notebook, many views

The Rio athlete notebook powers a publication report, a linked data explorer,
and a Three.js briefing. All three presentations draw from the same analytical
source:

<StudioExample family="athletes" />

The **Notebook** tab renders the backing analytical document as static Marimo
HTML. The neighboring tabs run its purpose-built views through WebAssembly.

The report embeds a Marimo dropdown and rendered Polars result. The explorer
passes the complete athlete table to Svelte, Mosaic, vgplot, and DuckDB-WASM.
The briefing projects that table into Three.js and mounts the native sport
control. All three views use the notebook's roster and measures.

## Analytical context stays with the notebook

The notebook owns data loading, metrics, reusable filters, and shared results.
Each view owns purpose-specific layout, wording, browser interaction, and
browser libraries.

The notebook stays readable as an analysis while each frontend uses the
interaction model its task needs.

## Create a view for each purpose

```console
marimo-studio view create dashboard --target analysis.py
marimo-studio view create report --target analysis.py
```

Both views read the same notebook results. Their source trees, dependencies,
builds, and last successful artifacts remain independent.

Set the main route in the notebook configuration:

```toml
[tool.marimo-studio]
default = "dashboard"
```

The default view opens at `/`. The report opens at `/report/`.

## Switch presentation, keep computation

The view menu saves pending source edits before selecting another view. The
active Python notebook session remains connected, so controls and computed
results continue from their current values.

A static export gives each view a self-contained directory. Place linked views
as siblings and use relative links such as `../report/index.html`. The link
remains valid at a local root, beneath a deployment base path, and after copying
the parent directory.

Use [the frontend guide](frontend-options.md) to choose a starter for each
view. Use [the live examples](../examples/index.md) to compare eight finished
presentations.
