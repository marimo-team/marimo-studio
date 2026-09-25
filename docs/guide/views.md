---
title: Create and manage views
description: Create, switch, and remove the named views of a notebook.
---

# Create and manage views

A view is the stable name and URL for one interface backed by a notebook. Add a
view when the same analysis needs a different layout, explanation, interaction,
or audience.

<StudioViewStack family="athletes" />

The [Rio athletes example](../examples/athletes.md) has `overview`, `explorer`,
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
