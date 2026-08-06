---
title: Create your first view
description: Add a dashboard to a saved Marimo notebook and render one live notebook output.
---

# Create your first view

Add a dashboard to a saved [marimo](https://marimo.io/) notebook, open it
beside the native editor, and replace the starter page with one focused output.

The commands use `analysis.py` as the notebook path. You need Python 3.11 or
newer and [uv](https://docs.astral.sh/uv/).

## Add the dashboard

```console
uvx marimo-studio view add dashboard analysis.py
```

Studio adds its notebook configuration and creates:

```text
analysis.py
__marimo__/
  studio/
    analysis/
      dashboard/
        index.html
        app.css
```

The starter document places every notebook cell in source order. This gives
you a working preview before you choose the final content.

If the notebook already contains `[tool.marimo-studio]` and its view directory
is empty, open the notebook with `marimo edit`. Studio presents **Create the
first view** and uses the configured `default` name.

## Open the workspace

```console
uv run --with marimo-studio marimo edit analysis.py --sandbox
```

Marimo opens its editor beside the selected view. Choose **Build** to keep both
visible. Open **HTML & CSS** from the workspace menu when you want the view
source and preview together.

Change a notebook control and confirm that the starter view updates. The
Server preview and editor use the same Python session.

## Name the output

Inspect cells that end with a displayed result:

```console
uvx marimo-studio inspect analysis.py --display
```

Use a native Marimo cell name when the intended cell already has one. Bind an
anonymous cell to a stable alias when it does not:

```console
uvx marimo-studio bind summary analysis.py --cell 3
```

Replace `3` with the zero-based index reported by `inspect`.

## Place the output

Open `index.html` and replace the contents of `#app-shell`:

```html
<main id="app-shell" class="studio-view grid gap-6">
  <header>
    <p class="studio-eyebrow">Quarterly review</p>
    <h1 class="text-4xl font-semibold tracking-tight">Revenue at a glance</h1>
  </header>

  <section class="studio-card p-5" aria-labelledby="summary-title">
    <h2 id="summary-title" class="text-lg font-semibold">Summary</h2>
    <marimo-cell name="summary"></marimo-cell>
  </section>
</main>
```

Save the file. Studio refreshes the authored shell and mounts the live Marimo
output under **Summary**. Change a notebook control again and confirm that the
summary reacts.

## Check the view

Validate the document, cell alias, and value selectors:

```console
uvx marimo-studio check analysis.py
```

Run projected cells and resolve projected values before sharing:

```console
uvx marimo-studio check analysis.py --runtime
```

The runtime check executes notebook code. It can perform the same file,
network, database, and data access as the projected cells.

Continue with [Create and manage views](views.md) when another audience needs
its own page, or [Design a view](design-views.md) to add values, styling, and
browser behavior.
