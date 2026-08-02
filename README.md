# Marimo Studio

Build focused dashboards, reports, and tools from a
[Marimo](https://marimo.io/) notebook. Keep calculations, reactive controls,
plots, tables, and [anywidgets](https://anywidget.dev/) in Python, then arrange
the cells and values each audience needs in custom HTML and CSS views. One
notebook can serve several views.

## Try the example

From a checkout with [uv](https://docs.astral.sh/uv/) installed, run:

```console
uv run marimo-studio examples/analysis.py
```

The workspace opens with the notebook and finished dashboard side by side.
Change the scenario or quarter and watch the metrics, summary, and table update
from the same Python session. Split either pane when you want the HTML or CSS
source in the workspace. Open **Pane**, choose **Add Source**, then place it on
any side of the current pane.

The [example](https://github.com/peter-gy/marimo-studio/tree/main/examples)
pairs an ordinary notebook with one view under
`examples/__marimo__/studio/analysis/dashboard/`.

## Build a view

Open any notebook with Studio:

```console
uvx marimo-studio analysis.py
```

Studio creates a blank `dashboard` view beside the notebook. Place complete
cell outputs with `<marimo-cell>` and JSON-compatible Python values with
`mo-value`. Controls and widgets remain connected to the notebook kernel.
In edit mode, a control change in the editor or any attached preview updates
the other open views.

Keep the editor and preview open while you or an agent edits the view. Saved
HTML and CSS refresh around the running Python session. The CLI exposes
notebook discovery and runtime validation as structured output:

```console
uvx marimo-studio inspect analysis.py --display --format json
uvx marimo-studio check analysis.py --runtime --format json
```

Create another view from the same notebook:

```console
uvx marimo-studio view add executive analysis.py
```

View source stays under `__marimo__/studio/` with the notebook. Python remains
the source of calculations and reactive behavior.

## Run the view

Serve the default view through Marimo's server:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless
```

Visitors receive the custom view backed by a live Python session. Marimo keeps
ownership of notebook execution, authentication, sessions, and server APIs.

Use Python 3.11 or newer with Marimo 0.23.16 or newer.

## Documentation

- [Create your first view](https://peter-gy.github.io/marimo-studio/getting-started)
- [Design a view](https://peter-gy.github.io/marimo-studio/build-pages)
- [Share a view](https://peter-gy.github.io/marimo-studio/deployment)
- [CLI and configuration](https://peter-gy.github.io/marimo-studio/reference)
- [Python API](https://peter-gy.github.io/marimo-studio/python-api)
