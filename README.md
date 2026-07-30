# Marimo Studio

Turn a [Marimo](https://marimo.io/) notebook into focused dashboards, reports,
and tools. Keep calculations, reactive controls, plots, tables, and
[anywidgets](https://anywidget.dev/) in the notebook, then arrange the outputs
each audience needs in custom HTML and CSS views. Build several views from the
same notebook for different audiences.

## See it work

From a checkout with [uv](https://docs.astral.sh/uv/) installed, run:

```console
uv run marimo-studio examples/analysis.py
```

The native notebook editor opens beside a finished dashboard. Change the
scenario or quarter and watch the metrics, summary, and table update from the
same Python session.

Open the
[complete example](https://github.com/peter-gy/marimo-studio/tree/main/examples)
to compare the notebook with its HTML and CSS view. The notebook uses ordinary
named cells. The view chooses where their outputs and values appear.

## Keep each concern in its natural place

| Notebook                             | Studio view                              |
| ------------------------------------ | ---------------------------------------- |
| Data loading and Python calculations | Page structure and navigation            |
| Reactive dependencies                | Audience-specific wording                |
| Controls, plots, tables, and widgets | Branding, spacing, and responsive layout |
| Reusable values for presentation     | Which results appear and when            |

Notebook cells stay ordinary Marimo cells. View source lives beside the
notebook, so you or an agent can redesign the interface without moving the
analysis into a separate application.

## Work beside an agent

Keep the editor and preview open while an agent edits the view. Saved HTML and
CSS changes appear in the preview while your current Python session keeps
running.

The CLI gives agents a structured path from discovery to verification:

```console
uv run marimo-studio inspect examples/analysis.py --display --format json
uv run marimo-studio check examples/analysis.py --runtime --format json
```

Create another view when one audience needs a different experience:

```console
uv run marimo-studio view add executive examples/analysis.py
uv run marimo-studio view add operations examples/analysis.py
```

Both views can reuse the same notebook cells, reactive state, and shared
aliases.

## Share the result

Serve the default view through Marimo:

```console
uv run marimo run examples/analysis.py \
  --no-sandbox \
  --headless
```

Visitors receive the custom view backed by a live Python session. Marimo keeps
ownership of notebook execution, authentication, kernel sessions, and its
server API.

Use Python 3.11 or newer with Marimo 0.23.14 or newer.

## Continue

- [Create your first view](https://peter-gy.github.io/marimo-studio/getting-started)
- [Design a view](https://peter-gy.github.io/marimo-studio/build-pages)
- [Share a view](https://peter-gy.github.io/marimo-studio/deployment)
- [CLI and configuration](https://peter-gy.github.io/marimo-studio/reference)
- [Python API](https://peter-gy.github.io/marimo-studio/python-api)
