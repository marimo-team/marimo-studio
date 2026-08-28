---
title: Create your first page
description: Create a web page from a saved marimo notebook and see notebook output update inside it.
---

# Create your first page

Start with a saved marimo notebook named `analysis.py`. Create a page for its
main audience:

```console
uvx marimo-studio view create dashboard --target analysis.py
```

Studio creates `index.html` beside the notebook and prints the command that
opens the authoring workspace. Run it:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Choose **Develop**. The workspace brings three parts of the result into one
place:

- **Notebook** runs Python and owns the reactive computation.
- **Source** controls the page structure, wording, styles, and browser behavior.
- **Preview** shows the page your audience will use.

Studio calls this named page a **view**. The first view is named `dashboard`.

## Place a notebook result on the page

Add a named result cell to the notebook:

```python
@app.cell
def sales_summary():
    import marimo as mo

    message = mo.md("## Revenue is on target")
    message
    return (message,)
```

Open `index.html` in Source and place that complete cell inside `#app-shell`:

```html
<main id="app-shell">
  <marimo-cell name="sales_summary"></marimo-cell>
</main>
```

Save the file. Studio builds the page and Preview shows **Revenue is on
target**. Future notebook runs update the result through marimo's reactive
runtime.

If the source cannot build, Preview keeps the last successful page and Source
shows the problem beside the affected file.

## Run the page

Start the notebook as an application:

```console
uvx --with marimo-studio marimo run analysis.py --sandbox
```

The dashboard opens at `/`. A second named page receives its own route.

Continue with [Create pages for different audiences](views.md) or [Place
notebook results on a page](notebook-results.md).
