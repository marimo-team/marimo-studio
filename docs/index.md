# Build a custom view for a Marimo notebook

Choose the cells and Python values an audience needs, then arrange them in a
custom web page. The [Marimo](https://marimo.io/) notebook keeps calculations,
reactive controls, plots, tables, and widgets. Studio keeps each view in HTML
and CSS beside the notebook.

```console
uvx marimo-studio analysis.py
```

The command opens the Marimo editor and a live view preview in one workspace.
Saved view changes refresh around the running Python session.

## Keep Python and presentation together

| Notebook | Studio view |
| --- | --- |
| Data loading and calculations | Page structure and navigation |
| Reactive dependencies | Audience-specific wording |
| Controls, plots, tables, and widgets | Layout, branding, and responsive design |
| Presentation values | Which results appear |

Place a complete cell output with:

```html
<marimo-cell name="forecast_chart"></marimo-cell>
```

Place a JSON-compatible Python value in page text with:

```html
<time mo-value="report.updated_at"></time>
```

Both remain connected to the notebook kernel. While editing, a control change
in the notebook or an attached preview updates the other open views and reruns
the affected cells.

## Build for each audience

One notebook can serve several views:

```console
uvx marimo-studio view add executive analysis.py
uvx marimo-studio view add operations analysis.py
```

Views share notebook cells and aliases while keeping separate HTML, CSS, and
static files.

## Continue

- [Create your first view](getting-started.md) from an existing notebook.
- [Design a view](build-pages.md) with cells, values, loading space, and
  on-demand regions.
- [Share a view](deployment.md) through Marimo's server.
- Look up commands and settings in [CLI and configuration](reference.md).
- Use the [Python API](python-api.md) for notebook inspection or ASGI
  composition.
