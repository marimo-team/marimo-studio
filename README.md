<p align="center">
  <a href="https://peter-gy.github.io/marimo-studio/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://peter-gy.github.io/marimo-studio/brand/marimo-studio-lockup-horizontal-dark.svg">
      <img alt="Marimo Studio" src="https://peter-gy.github.io/marimo-studio/brand/marimo-studio-lockup-horizontal-light.svg" width="620">
    </picture>
  </a>
</p>

<p align="center">
  <a href="https://github.com/peter-gy/marimo-studio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/peter-gy/marimo-studio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/marimo-studio.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/marimo-studio.svg"></a>
</p>

<p align="center"><strong>Tune your notebook for every audience.</strong></p>

Keep calculations, reactive controls, plots, tables, downloads, and
[anywidgets](https://anywidget.dev/) in one [Marimo](https://marimo.io/)
notebook. Tune the interface for each audience as a focused dashboard, report,
or tool in custom HTML and CSS, with every view connected to the notebook's
live state.

## Try the example

Clone the repository, then open the included notebook:

```console
make install build
uv run marimo edit examples/analysis.py --no-sandbox
```

The browser opens the notebook beside its dashboard. Choose **Server** to run
both panes through the editor's Python session. Switch the preview to
**WebAssembly** to reveal the copy that Studio prepared in a background
Pyodide worker. Studio keeps native Marimo controls such as the scenario and
quarter synchronized while each runtime updates its own reactive graph.

Open **HTML & CSS** and inspect the dashboard's three view files. Layout and
responsive behavior live in Wind4 classes in `index.html`, shared visual
tokens live in `theme.css`, and loading dimensions use arbitrary property
utilities on each projected cell. `app.css` remains available for selectors
that need ordinary CSS. Change the scenario, edit a utility class or
`--primary`, then save. The refreshed view keeps the current control values
and rendered cell state.

For a multi-view workflow, open the collection research example:

```console
uv run --with pyobservablejs --with polars \
  marimo edit examples/nga_collection.py --no-sandbox
```

Narrow the corpus, select works in **Study**, and open **Packet**. The three
pages apply separate semantic themes and responsive layouts to one notebook
session, so the filters and ordered selection carry through the workflow.

## Create a view

Add a dashboard to an existing notebook, then open it through Marimo:

```console
uvx marimo-studio view add dashboard analysis.py
uv run --with marimo-studio marimo edit analysis.py --sandbox
```

The new view starts with every notebook cell in source order. Studio gives you
the Marimo editor, view source editors, and a live preview in one workspace.
Write [utility classes](https://unocss.dev/presets/wind4/) directly in
`index.html`, tune semantic light and dark tokens in `theme.css`, and keep
bespoke rules in `app.css`. Saved source changes refresh around the running
notebook.

Place a named cell or a JSON-compatible Python value in the view:

```html
<marimo-cell name="revenue_chart"></marimo-cell> <time mo-value="report.updated_at"></time>
```

Add more views when the same notebook needs a different page for another
audience.

## Share a view

Serve the notebook with Marimo:

```console
uv run --with marimo-studio marimo run analysis.py --sandbox --headless
```

The default view opens at `/`. A view named `report` opens at `/report/`. Each
browser receives its own Marimo run session.

Export a view when the notebook can run in WebAssembly and the destination is
a static host:

```console
uvx marimo-studio export analysis.py --view report --output dist/report
python -m http.server --directory dist/report
```

Marimo Studio supports Python 3.11 or newer and Marimo 0.23.16 or newer.

## Learn more

- [Create your first view](https://peter-gy.github.io/marimo-studio/getting-started)
- [How Marimo Studio works](https://peter-gy.github.io/marimo-studio/how-it-works)
- [Design a view](https://peter-gy.github.io/marimo-studio/design-views)
- [Share a view](https://peter-gy.github.io/marimo-studio/share-views)
- [Commands and configuration](https://peter-gy.github.io/marimo-studio/reference)
- [Python API](https://peter-gy.github.io/marimo-studio/python-api)
