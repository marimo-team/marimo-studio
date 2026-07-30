# Marimo notebooks, custom views

Marimo Studio places selected notebook outputs in authored HTML while Marimo
keeps the Python kernel, reactive graph, controls, plots, tables, and widgets
live behind the page.

```console
uvx marimo-studio analysis.py
```

The command opens the native Marimo editor beside a live custom view. Edit the
view shell and CSS while the preview keeps its current kernel session.

```html
<main id="app-shell">
  <h1>Forecast</h1>
  <marimo-cell name="forecast_chart"></marimo-cell>
  <p>Updated <time mo-value="report.updated_at"></time></p>
</main>
```

One notebook can back several views from the same cells and bindings:

```console
uvx marimo-studio view add executive analysis.py
uvx marimo-studio view add operations analysis.py
```

Start with [Getting started](getting-started.md). Continue with
[Build a view](build-pages.md) for cell hosts, kernel values, HTMX, loading
space, and theming.
