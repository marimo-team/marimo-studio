---
title: Create and manage views
description: Create, rename, switch, and remove the named views of a notebook, and choose its default view.
---

# Create and manage views

A view is the stable name and URL for one interface backed by a notebook. Add a
view when the same analysis needs a different layout, explanation, interaction,
or audience.

<StudioViewStack family="athletes" />

The [Rio 2016 athletes example](../examples/athletes.md) has `overview`, `explorer`,
and `field` views. Each view has its own project, build, and last successful
artifact. Keep shared measures and reusable controls in the notebook, and
layout, wording, and browser dependencies in each view.

## Create another view

Open the view menu and choose **New view**. Enter a lowercase name, choose a
starter, and inspect **Files created** before confirming. Studio saves pending
Source edits before switching to the new view.

The equivalent command is:

```console
marimo-studio view create report --target analysis.py
```

## Choose the default view

The default view opens at `/`. The `report` view opens at `/report/`. Serve
`report` at the main route with:

```console
marimo-studio view default report --target analysis.py
```

Studio stores the choice as `default` in the notebook configuration:

```toml
[tool.marimo-studio]
default = "report"
```

## Rename a view

Rename a view to give its URL and menu entry a new name:

```console
marimo-studio view rename report summary --target analysis.py
```

The project keeps its source, artifacts, and build history, and a default view
stays the default. Links to `/report/` stop resolving, so update any view that
links to the old URL.

## Switch views

Choose a view from the view menu. Studio keeps the active Python runtime
session connected, so controls and computed results retain their current state.
Each Browser runtime view uses its own browser notebook instance.

If Source has pending edits, Studio saves them before the switch. A failed save
or unresolved source conflict keeps the current view selected for repair.

## Remove a view

Use the remove action beside a view name and confirm with **Remove**. Removal
permanently deletes the view project and its files. If the removed view was the
default, Studio names the replacement in the confirmation and promotes it to
the main route.

Studio keeps at least one view. Create a replacement before removing the last
one.

The terminal command follows the same contract:

```console
marimo-studio view remove report --target analysis.py
```

A running Studio server keeps the artifacts of views it serves in use, and the
terminal command then reports `view-in-use` with that server's process ID.
Remove the view from the Studio tab or from code mode in that notebook, which
lets the server release them first.

Use [Choose a frontend](frontend-options.md) to select a starter. Use [Navigate
and preserve state](navigation-and-sessions.md) when views link to one another
or share public query state.
