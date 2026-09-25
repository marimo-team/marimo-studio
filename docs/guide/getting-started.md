---
title: Create your first view
description: Open a saved Marimo notebook, create a view, and place one reactive result inside it.
---

# Create your first view

Start with Python 3.10 through 3.14, [uv](https://docs.astral.sh/uv/), and a saved
Marimo notebook such as `analysis.py`.

## Open Studio

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Marimo's `--sandbox` flag resolves the notebook's declared Python dependencies
with uv. Notebook code still has access to your files and network.

Click **Add view** in the Studio toolbar. Name the view `dashboard`, choose
**HTML document**, and review the files it will create. For an untitled notebook,
save it when prompted so the view has a stable location beside the notebook.

Notebook and Preview open side by side. The source action opens the view's
files beneath Preview. The starter page already shows every notebook cell that
displays output.

## Place a notebook result

You can [ask a coding agent](coding-agents.md) to shape the view around your
audience and task, or edit its source directly.

For a first manual change, add a cell named `sales_summary` in the notebook
editor. In the saved notebook file, it reads:

```python
@app.cell
def sales_summary():
    import marimo as mo

    summary = mo.md("## Revenue is on target")
    summary
    return (summary,)
```

If the notebook already imports `marimo as mo` in another cell, reuse that
import. Run the cell, then open `index.html` in Source and place its result
inside the existing `#app-shell`:

```html
<marimo-cell name="sales_summary"></marimo-cell>
```

Save the source. Preview shows **Revenue is on target**. Change the notebook
message and run the cell again to see the result update in the view.

The notebook owns the computation. The view owns the page around it. A frontend
build error keeps the last successful page visible while you repair the source.

## View project files

The default starter saves the view beside the notebook:

```text
analysis.py
__marimo__/studio/analysis/
  dashboard/
    view.toml
    index.html
    AGENTS.md
```

`view.toml` records the provider. `index.html` is the page source. `AGENTS.md`
gives coding agents the project's conventions. Add `DESIGN.md` to keep the
view's audience and visual direction with its source.

To create the same view from a terminal:

```console
uvx marimo-studio view create dashboard --target analysis.py
```

Add `--dry-run` to inspect the plan first. Creation can update the notebook's
Studio configuration, set the default view, and pin its Studio requirement.
The command prints the launch requirements for the chosen starter.

## Run the view

Run the notebook as an application:

```console
uvx --with marimo-studio marimo run analysis.py --sandbox
```

The default view opens at `/`. A second view named `report` opens at `/report/`.
Choose [Run or export a view](run-and-share.md) for hosting and static delivery.

Continue with [Place notebook results in a view](notebook-results.md) for
controls, rich outputs, and browser values, or [Choose a
frontend](frontend-options.md) for React, Svelte, slides, and other starters.
