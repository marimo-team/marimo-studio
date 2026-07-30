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

The command opens the native Marimo editor beside a blank `dashboard` preview.
Keep this browser window open while you edit the view.

On the first run, the command adds Studio setup to the notebook's PEP 723
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

The metadata records `marimo-studio` as an unversioned dependency and sets the
default view. Notebook code outside that block stays byte-identical. Unrelated
dependencies, uv sources, indexes, and Marimo settings remain in
place.

## Choose an output

List cells that display a result:

```console
uvx marimo-studio inspect analysis.py --display
```

A named cell appears with its name in the last column. For example:

```text
  3  bkHC   output  line 66   summary
     defines: summary_view
```

Use the cell name directly in a view. When the row ends with `cell 3`, give
that anonymous cell a stable alias:

```console
uvx marimo-studio bind summary analysis.py --cell 3
```

The alias belongs to the notebook and can be reused by every view.

## Place the output in the page

Open `__marimo__/studio/analysis/dashboard/index.html`. Replace its empty
`#app-shell` with:

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

Save the file. The preview refreshes around the current Python session and
renders the notebook output under **Summary**.

Add page-level styling in `app.css`:

```css
body {
  margin: 0;
  color: #202124;
  background: #f7f7f5;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

#app-shell {
  width: min(72rem, calc(100% - 2rem));
  margin: 0 auto;
  padding: 4rem 0;
}
```

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

An agent can inspect the notebook as structured data, edit the view files, and
validate the result while your editor and preview stay open:

```console
uvx marimo-studio inspect analysis.py --display --format json
uvx marimo-studio check analysis.py --runtime --format json
```

The notebook remains the source of Python behavior. The agent can focus on
page structure, copy, responsive layout, and which existing outputs belong in
the view.

## Add a view for another audience

Create an `executive` view:

```console
uvx marimo-studio view add executive analysis.py
uvx marimo-studio analysis.py --view executive
```

The new view lives at `__marimo__/studio/analysis/executive/` and can reuse the
`summary` alias. Keep the view directories in source control with the
notebook. See [CLI and configuration](reference.md#source-control) when the
repository ignores `__marimo__`.

Continue with [Design a view](build-pages.md) to combine complete cells,
individual Python values, loading space, and on-demand detail.
