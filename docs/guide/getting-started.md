---
title: Getting started
description: Open a marimo notebook with Studio, create an HTML view, find its files, and place a notebook result in it.
---

# Getting started

You need Python 3.10 through 3.14, [uv](https://docs.astral.sh/uv/), and a
[marimo](https://marimo.io/) notebook such as `analysis.py`. This page creates
a [view](../reference/glossary.md#view) named `dashboard`, an HTML page, and
places one notebook result in it.

## Open the notebook with Studio

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox --watch
```

`--sandbox` installs the notebook's declared dependencies with uv. It manages
packages and does not restrict what notebook code can access. `--watch`
reloads the notebook when another editor or a coding agent changes the file.

## Create a view

Click **Add view** in the Studio toolbar. Name the view `dashboard`, choose
**HTML document**, review the files it will create, and confirm. Save the
notebook first if Studio asks, so the view has a folder beside it. Once a
notebook has a view, the view menu offers **New view** for the next one.

Notebook and Preview open side by side. The new page already shows every
notebook cell that displays output.

## Look at the files

Studio saved the view as a
[view project](../reference/glossary.md#view-project), a folder named after
the notebook and the view:

```text
analysis.py
studio/analysis/
  dashboard/
    view.toml     the provider that builds this view
    index.html    the page
    AGENTS.md     conventions for coding agents
```

The folder is an ordinary HTML project. Edit `index.html` in Studio's Source
pane, which **Edit view source** opens beneath Preview, or in your own editor.
Studio watches the folder and rebuilds Preview whenever a file is saved.

Commit `studio/` with the notebook. Build output goes to
`__marimo__/studio/analysis/`, which Git ignores. Add a `DESIGN.md` to the view
project when the view has an audience and visual direction worth recording.

The same view can be created from a terminal:

```console
uvx marimo-studio view create dashboard --target analysis.py
```

## Place a notebook result

Add a cell named `sales_summary` to the notebook and run it. In the saved
notebook file it reads:

```python
@app.cell
def sales_summary(mo):
    summary = mo.md("## Revenue is on target")
    summary
    return (summary,)
```

A page names each notebook result it shows with a
[host](../reference/glossary.md#host), an element that Studio fills with that
result. Place the cell in `index.html` with a `<marimo-cell>` host, inside the
`<main id="app-shell">` element that holds the page's content:

```html
<marimo-cell name="sales_summary"></marimo-cell>
```

Save. Preview rebuilds and shows **Revenue is on target**. Change the message
in the notebook and run the cell again. The view updates without a rebuild,
because the page reads the cell's current output from the running notebook.

If a later edit breaks the build, Preview keeps the last page that built and
Source shows the error.

## Run the view

```console
uvx --with marimo-studio marimo run analysis.py --sandbox
```

The default view opens at `/`. A second view named `report` would open at
`/report/`.

## Next steps

- [How Studio works](../how-studio-works.md) explains what happened between
  saving `index.html` and seeing the result.
- [Place notebook results in a view](notebook-results.md) covers cells,
  outputs, and values in pages and PDFs.
- [Choose a format](formats.md) creates React, Svelte, Reveal.js, Quarto,
  Typst, and LaTeX views.
- [Run or export a view](run-and-share.md) publishes the view.
