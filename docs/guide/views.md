---
title: One notebook, many views
description: Keep shared analysis in one reactive notebook and give each task its own named view.
---

# One notebook, many views

A view is the stable name and URL for one interface backed by a notebook. Add a
view when the same analysis needs a different layout, explanation, interaction,
or audience.

<StudioExample family="athletes" />

The Rio athletes notebook supports three views. The report uses native Marimo
controls and a rendered [Polars](https://pola.rs/) table. The explorer passes
the full athlete table to [Svelte](https://svelte.dev/),
[Mosaic](https://uwdata.github.io/mosaic/), and
[DuckDB-WASM](https://duckdb.org/docs/stable/clients/wasm/overview). The field
briefing presents the same records through [Three.js](https://threejs.org/).

## Keep ownership clear

The notebook owns data loading, transformations, metrics, models, reusable
controls, and Python execution. Each view owns its view project, browser
dependencies, layout, wording, and interaction.

| Change                                  | Owner        |
| --------------------------------------- | ------------ |
| Correct a shared measure                | Notebook     |
| Add a reusable control                  | Notebook     |
| Change a chart library                  | View project |
| Rewrite an explanation for one audience | View project |

Each view has an independent build and last successful artifact. Building one
view leaves the notebook session and other views available.

## Create another view

Open the view menu and choose **New view**. Enter a lowercase name, choose a
starter, and inspect **Files created** before confirming. Studio saves pending
Source edits before switching to the new view.

The equivalent command is:

```console
marimo-studio view create report --target analysis.py
```

Set the main route in the notebook configuration:

```toml
[tool.marimo-studio]
default = "dashboard"
```

The default view opens at `/`. The `report` view opens at `/report/`.

## Switch views

Choose a view from the view menu. Studio keeps the active Python runtime
session connected, so controls and computed results retain their current state.
Each Browser runtime view uses its own browser notebook instance.

If Source has pending edits, Studio saves them before the switch. A failed save
or unresolved source conflict keeps the current view selected for repair.

## Remove a view

Use the remove action beside a view name and confirm **Remove view**. Removal
permanently deletes the view project and its files. If the removed view was the
default, Studio names the replacement in the confirmation and promotes it to
the main route.

Studio keeps at least one view. Create a replacement before removing the last
one.

The terminal command follows the same contract:

```console
marimo-studio view remove report --target analysis.py
```

Use [Choose a frontend](frontend-options.md) to select a starter. Use [Navigate
and preserve state](navigation-and-sessions.md) when views link to one another
or share public query state.
