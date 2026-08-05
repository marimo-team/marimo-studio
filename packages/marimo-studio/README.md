# Marimo Studio

**Tune your notebook for every audience.**

Keep calculations, reactive controls, plots, tables, downloads, and
[anywidgets](https://anywidget.dev/) in one [Marimo](https://marimo.io/)
notebook. Tune the interface for each audience as a focused dashboard, report,
or tool in custom HTML and CSS, with every view connected to the notebook's
live state.

```console
uvx marimo-studio view add dashboard analysis.py
uv run --with marimo-studio marimo edit analysis.py --sandbox
```

The new view starts with every notebook cell in source order. Use native cell
names and JSON-compatible Python values in the page:

```html
<marimo-cell name="revenue_chart"></marimo-cell> <time mo-value="report.updated_at"></time>
```

Read the [Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/)
for view design, sharing, configuration, and the Python API.
