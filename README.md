<p align="center">
  <a href="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/marimo-studio.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/marimo-studio.svg"></a>
</p>

# Marimo Studio

Marimo Studio turns one saved [marimo](https://marimo.io/) notebook into
focused web pages for different audiences. The notebook keeps the data,
computation, controls, and reusable results. Each page chooses how those results
are arranged and how its audience interacts with them.

## Create your first page

Start with a saved notebook such as `analysis.py`:

```console
uvx marimo-studio view create dashboard --target analysis.py
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

The first command creates the page source beside the notebook. The second opens
marimo with three connected surfaces:

- **Notebook** for Python and reactive computation
- **Source** for the page's HTML, styles, and browser code
- **Preview** for the page your audience will use

Choose **Develop** to see all three. Saving Source rebuilds Preview, while a
failed build leaves the last successful page available.

![Notebook, page source, and Preview together in Develop](apps/docs/public/screenshots/studio-develop.png)

Studio calls each named page a **view**. Add another view when the same notebook
needs a different layout, explanation, or interaction for another audience.

## Choose how to build the page

The default page keeps its HTML, styles, and browser code in one editable file.
It is the shortest path for reports, dashboards, and focused tools.

Choose React or Svelte when the page benefits from components and a larger
frontend source tree. Use the `marimo-studio/react:reveal` starter for a React
slide deck. Install `marimo-studio[deno]` in that environment so Studio can
build those files with the pinned Deno toolchain.

Teams can connect another frontend build when an existing project should remain
the source of the page. The [frontend integration
reference](https://marimo-team.github.io/marimo-studio/reference/provider-api)
defines the small Python contract that creates, inspects, and builds that
source.

## Place notebook results anywhere

Page source can place a complete cell, one rendered Python object, or a
JSON-compatible value:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

Marimo continues to own reactive execution, controls, widgets, and rich output
rendering. Studio controls where each result appears.

## Author with a coding agent

The package includes an Agent Skill and a code-mode Python API. A coding
agent can inspect notebook cells and page source, make an edit without
overwriting a newer save, build the page, show it in Studio, and verify the
rendered result.

Human and agent edits use the same source files and conflict protection. Read
[Author with a coding
agent](https://marimo-team.github.io/marimo-studio/guide/coding-agents) for the
complete workflow.

## Run or publish

Use `marimo run` when the notebook needs Python packages, local files,
databases, or server credentials. Browser execution and static export are
available when the notebook and its data can run in Pyodide.

Read [Run or publish a
page](https://marimo-team.github.io/marimo-studio/guide/run-and-share) before
choosing where the notebook will execute.

## Explore the repository example

The National Gallery of Art example uses one notebook to produce a collection
brief, an artwork browser, and an editorial story:

```console
make setup
uv run --with polars --with pyobservablejs marimo edit examples/nga.py
```

See the [Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/)
for the guided workflow, the example, and exact API contracts.

## Compatibility

Marimo Studio 0.1.0 requires Python 3.10 or newer and Marimo 0.24.0. React,
Reveal.js, and Svelte authoring use the optional Deno 2.9.5 dependency.

## License

Marimo Studio is licensed under the [Apache License 2.0](LICENSE).
