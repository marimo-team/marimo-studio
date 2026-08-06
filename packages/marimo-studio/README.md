# Marimo Studio

**Tune your notebook for every audience.**

Keep calculations, reactive controls, plots, tables, downloads, and
[anywidgets](https://anywidget.dev/) in one [marimo](https://marimo.io/)
notebook. Create focused views with plain HTML and CSS that you and your coding
agent already write. Marimo keeps notebook logic, controls, and outputs live.

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
