# Turn a notebook into a focused app

Choose the cells and Python values your audience needs, then arrange them in a
custom web view. Your [Marimo](https://marimo.io/) notebook keeps the
calculations, reactive graph, controls, plots, tables, and widgets. You control
what appears, how the page is organized, and which experience each audience
receives.

```console
uvx marimo-studio analysis.py
```

The command opens the native editor beside a live preview. Keep working in the
notebook while you or an agent shapes the view in HTML and CSS.

## Start from the notebook that already works

Start with the outputs your notebook already produces. Place a complete cell
in the view:

```html
<marimo-cell name="forecast_chart"></marimo-cell>
```

Place a Python value inside ordinary page text:

```html
<p>
  Updated <time mo-value="report.updated_at"></time>
</p>
```

Your controls and widgets stay connected to the Python kernel. An interaction
reruns the affected cells and updates the mounted output.

## Shape one source for several audiences

Create a separate view when the same analysis needs a different page,
selection of results, or level of detail:

```console
uvx marimo-studio view add executive analysis.py
uvx marimo-studio view add operations analysis.py
```

| Audience | View can emphasize |
| --- | --- |
| Executives | Key measures, conclusions, and a compact chart |
| Operations | Current controls, detailed tables, and downloads |
| Analysts | Diagnostics, comparisons, and deeper supporting output |

Every view uses the notebook's cells and shared aliases. Presentation changes
stay in the view files, so the notebook remains the source of calculations.

## Choose the experience you want to share

| Experience | Best fit |
| --- | --- |
| Native Marimo app | The notebook's existing layout already matches the audience's task |
| Marimo Studio view | The audience needs custom structure, wording, visual design, or several purpose-specific views |
| Static artifact | The audience needs a fixed result and no live Python interaction |

Use the regular editor while you build a view. When you run the notebook,
visitors land on the custom view and receive a live Python session.

## Build and share

- [Create your first view](getting-started.md) from an existing notebook.
- [Design a view](build-pages.md) with cells, values, loading space, and
  on-demand detail.
- [Share a view](deployment.md) through Marimo's server.
- Use [CLI and configuration](reference.md) for exact commands and settings.
- Use the [Python API](python-api.md) to inspect notebooks or build an ASGI app.
