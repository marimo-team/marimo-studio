# Marimo Studio

Marimo Studio turns selected outputs from a
[Marimo](https://marimo.io/) notebook into a custom web view while Marimo
keeps Python, reactive state, controls, plots, tables, and
[anywidgets](https://anywidget.dev/) live behind the page.

Run:

```console
uvx marimo-studio analysis.py
```

Studio opens the native notebook editor beside a live custom view. The first
run adds notebook-local configuration and creates a blank canvas at:

```text
__marimo__/studio/analysis/dashboard/
  index.html
  app.css
```

Inspect the notebook and bind an anonymous displayed cell when needed:

```console
uvx marimo-studio inspect analysis.py --display
uvx marimo-studio bind summary analysis.py --cell 12
```

Place the output in `index.html`:

```html
<main id="app-shell">
  <h1>Analysis</h1>
  <marimo-cell name="summary"></marimo-cell>
</main>
```

Marimo renders the cell through its regular browser runtime. Controls and
widgets remain connected to the Python kernel. Use
[HTMX](https://htmx.org/) for request-driven fragments and DOM swaps.

Deploy the view through Marimo:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless
```

## Documentation

- [Getting started](docs/getting-started.md)
- [Build a view](docs/build-pages.md)
- [Deploy](docs/deployment.md)
- [Reference](docs/reference.md)
- [Python API](docs/python-api.md)

Repository architecture and release procedures live in the
[development docs](development_docs/README.md).
