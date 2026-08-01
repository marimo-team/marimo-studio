# Create your first view

Create a live dashboard from one displayed notebook cell. Keep the Marimo
editor open, place the cell in a custom page, and verify the result against the
running Python kernel.

## Before you start

You need:

- A saved [Marimo](https://marimo.io/) notebook
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)

The example uses `analysis.py` and a displayed cell named `summary`.

## Open the notebook and view together

Run:

```console
uvx marimo-studio analysis.py
```

The command opens one workspace with the Marimo notebook on the left and its
live preview on the right. Keep this browser window open while you work. To
edit HTML or CSS in Studio, open **Pane** in either pane, choose **Add Source**,
then place it on the left, right, above, or below.

On the first run, the command configures Studio in the notebook's PEP 723
metadata and creates:

```text
analysis.py
__marimo__/
  studio/
    analysis/
      dashboard/
        index.html
        app.css
```

The metadata records `marimo-studio` as an unversioned dependency and selects
the default view. Notebook code outside the PEP 723 block stays byte-identical.

## Choose an output

List cells that display a result:

```console
uvx marimo-studio inspect analysis.py --display
```

Use a native cell name directly in a view. When a row ends with `cell 3`, give
that anonymous cell a stable alias:

```console
uvx marimo-studio bind summary analysis.py --cell 3
```

The alias belongs to the notebook and can be reused by every view.

## Place the output in the page

Select **HTML** in the Source pane. Replace its empty `#app-shell` with:

```html
<main id="app-shell">
  <header>
    <p>Quarterly review</p>
    <h1>Revenue at a glance</h1>
  </header>

  <section aria-labelledby="summary-title">
    <h2 id="summary-title">Summary</h2>
    <marimo-cell name="summary"></marimo-cell>
  </section>
</main>
```

Studio saves the edit to
`__marimo__/studio/analysis/dashboard/index.html`. The preview refreshes around
the current Python session and renders the notebook output under **Summary**.

You can edit the same file in another editor. Studio follows changes from disk
and keeps the browser editor current. If both editors change the file before a
save completes, Studio shows both versions and asks which one to keep.

Change a notebook control or rerun the cell that feeds `summary`. The mounted
output follows the notebook's reactive update.

## Validate the view

Run a static check while editing:

```console
uvx marimo-studio check analysis.py
```

Run the runtime check before sharing:

```console
uvx marimo-studio check analysis.py --runtime
```

The runtime check executes the projected cells and reads the Python values
referenced by the view. It can perform the file, network, database, and data
access defined by those notebook cells.

## Let an agent shape the interface

An agent can inspect the notebook as structured data, edit the same view files,
and validate the result while your notebook, source editor, and preview stay
open:

```console
uvx marimo-studio inspect analysis.py --display --format json
uvx marimo-studio check analysis.py --runtime --format json
```

The agent can focus on page structure, wording, responsive layout, and which
existing outputs belong in the view.

## Add a view for another audience

Open the view menu beside `dashboard`, select **New view**, and enter
`executive`. Studio opens the new HTML above its live preview and keeps the
notebook beside both. The starter view contains every notebook cell in source
order.

The equivalent command is:

```console
uvx marimo-studio view add executive analysis.py
```

The new view lives at `__marimo__/studio/analysis/executive/` and can reuse the
`summary` alias. Keep view directories in source control with the notebook.
See [Source control](reference.md#source-control) when the repository ignores
`__marimo__`.

The same menu removes views. Studio shows the files it will delete before the
removal runs.

Continue with [Design a view](build-pages.md) to combine complete cells,
individual Python values, loading space, and on-demand detail.
