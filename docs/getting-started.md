# Create your first view

Start with a saved [Marimo](https://marimo.io/) notebook, Python 3.11 or newer,
and [uv](https://docs.astral.sh/uv/). The commands below use `analysis.py`.

## Add a dashboard

```console
uvx marimo-studio view add dashboard analysis.py
```

The command adds Studio to the notebook's PEP 723 dependencies and creates:

```text
analysis.py
__marimo__/
  studio/
    analysis/
      dashboard/
        index.html
        theme.css
        app.css
```

The starter page contains every notebook cell in source order, so the first
preview already shows the available outputs.

## Open Studio through Marimo

```console
uv run --with marimo-studio marimo edit analysis.py --sandbox
```

Marimo opens the Studio workspace at its regular server URL. The notebook is
on the left and the selected view is on the right. Use **Notebook** or
**Preview** to give one pane the full canvas. Open **HTML & CSS** from the
workspace menu to edit `index.html`, `theme.css`, or `app.css` beside the live
preview.

Use the runtime control in the toolbar to test both execution modes:

- **Server** connects the preview to the editor's Python kernel. Controls and
  widget models stay synchronized between both panes.
- **WebAssembly** runs a separate copy of the notebook in a Pyodide worker.
  Studio synchronizes JSON-compatible values from native Marimo controls such
  as sliders, dropdowns, and switches. Each kernel reruns its own reactive
  graph. Cell output, tables, and anywidgets stay interactive in the preview.
  Anywidget state belongs to that Pyodide kernel.

Studio starts the WebAssembly preview in the background while **Server** is
selected. The runtime control reveals that preview immediately and reports its
startup status until it is ready. Both runtime documents remain mounted as you
switch views and modes.

For another arrangement, open the workspace menu and choose **Open saved
layout**. Choose **Arrange panes** to place Notebook, HTML/CSS, and Preview
beside, above, or below one another.

## Choose a notebook output

Inspect cells that display a result:

```console
uvx marimo-studio inspect analysis.py --display
```

Use a native Marimo cell name directly. Bind an anonymous cell when the view
needs a stable name:

```console
uvx marimo-studio bind summary analysis.py --cell 3
```

The cell index above is an example. Use the index reported by `inspect`.

## Place the output

Open **HTML & CSS**, select **index.html**, and replace the contents of
`#app-shell`:

```html
<main id="app-shell" class="studio-view grid gap-6 lg:grid-cols-2">
  <header class="lg:col-span-2">
    <p class="studio-eyebrow">Quarterly review</p>
    <h1 class="text-4xl font-semibold tracking-tight">Revenue at a glance</h1>
  </header>

  <section class="studio-card p-5" aria-labelledby="summary-title">
    <h2 id="summary-title">Summary</h2>
    <marimo-cell name="summary"></marimo-cell>
  </section>
</main>
```

Studio saves the file at
`__marimo__/studio/analysis/dashboard/index.html`. The preview refreshes and
renders the notebook output under **Summary**.

Change a control in the notebook or preview. With **Server**, Marimo propagates
native control and anywidget model changes through the shared session. With
**WebAssembly**, Studio mirrors native control values between kernels and each
kernel reruns the affected cells. Anywidget comm state belongs to the runtime
that created the model. Build the same native controls in the same order in
both runtimes so Studio can match each value to its counterpart.

You can also edit all three view files in another editor. Studio follows
changes from disk. If the browser and another editor change the same file,
Studio shows both versions for an explicit choice.

## Check the view

Validate templates, cell names, bindings, and value selectors:

```console
uvx marimo-studio check analysis.py
```

Execute projected cells and resolve projected values before sharing:

```console
uvx marimo-studio check analysis.py --runtime
```

The runtime check can perform the file, network, database, and data access used
by those cells.

Continue with [Create and manage views](views.md) for another audience or
[Design a view](design-views.md) for values, loading space, theming, and HTMX.
