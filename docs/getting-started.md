# Getting started

Start with a saved [Marimo](https://marimo.io/) notebook and
[uv](https://docs.astral.sh/uv/).

## Open Studio

Pass the notebook directly:

```console
uvx marimo-studio analysis.py
```

Studio opens the regular Marimo editor and a live custom view in one browser
workspace. The first run adds the invoked `marimo-studio` release and
`[tool.marimo-studio]` to the notebook's PEP 723 metadata. It also creates:

```text
analysis.py
__marimo__/
  studio/
    analysis/
      dashboard/
        index.html
        app.css
```

Notebook code outside the PEP 723 block stays byte-identical. Existing
dependencies, uv sources, indexes, and `[tool.marimo.*]` settings remain in
the metadata.

The view directory is authored source. Add `__marimo__/studio/` to version
control with the notebook. The [configuration reference](reference.md#source-control)
contains an ignore exception for repositories that ignore `__marimo__`.

## Find notebook outputs

Inspect cells with displayed expressions:

```console
uvx marimo-studio inspect analysis.py --display
```

A named Marimo cell works directly in a view. Bind an anonymous cell to a
stable alias with its zero-based index:

```console
uvx marimo-studio bind summary analysis.py --cell 12
```

Runtime inspection executes the notebook and reports output MIME types and
JSON-compatible values:

```console
uvx marimo-studio inspect analysis.py --runtime
```

Add `--format json` when an agent or script consumes the result. Runtime
inspection performs the file, network, database, and data-access operations
defined by the notebook.

## Build the first view

Edit `__marimo__/studio/analysis/dashboard/index.html` as a complete HTML
document:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Analysis dashboard</title>
    <link
      rel="stylesheet"
      href="./_marimo-studio/views/dashboard/static/app.css"
    >
  </head>
  <body>
    <main id="app-shell">
      <h1>Analysis</h1>
      <marimo-cell name="summary"></marimo-cell>
    </main>
  </body>
</html>
```

Every cell and value host belongs inside the single `#app-shell` element. HTML
changes replace that shell. CSS changes refresh independently. The preview
keeps its current kernel and widget models.

## Add another view

One notebook can serve several presentations:

```console
uvx marimo-studio view add executive analysis.py
uvx marimo-studio view list analysis.py
```

Open the new view in Studio:

```console
uvx marimo-studio analysis.py --view executive
```

The view lives at `__marimo__/studio/analysis/executive/` and shares the
notebook's cell bindings.

## Validate

Check templates, cell bindings, runtime outputs, and projected values:

```console
uvx marimo-studio check analysis.py --runtime
```

Continue with [Build a view](build-pages.md) for value selectors, HTMX
fragments, loading space, and theming.
