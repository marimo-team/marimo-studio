<p align="center">
  <a href="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/marimo-studio.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/marimo-studio.svg"></a>
</p>

# Marimo Studio

**One notebook. A studio for every view.**

Marimo Studio keeps one reproducible [marimo](https://marimo.io/) notebook as
the analytical model and lets you build a purpose-built web view for each job.
The notebook keeps data access, transformations, controls, and reusable results
together as one reactive Python program. Each named view owns its frontend
source, layout, and interaction while drawing from notebook cells, outputs, and
values.

> **0.1 status:** Marimo Studio 0.1.0 is the first public release. The
> notebook-to-view workflow, projection elements, and last-successful build
> behavior are supported product contracts. Before 1.0, CLI, Python, provider,
> and saved configuration contracts may change between minor releases. Pin
> Studio and third-party view providers in saved projects. Read [Compatibility
> and support](https://marimo-team.github.io/marimo-studio/reference/compatibility)
> before adopting Studio in a maintained project.

Agentic coding makes interfaces quick to create. The analysis behind them still
takes human attention. Marimo Studio keeps that analysis as the durable
analytical model behind every view. Read [Why
Studio?](https://marimo-team.github.io/marimo-studio/why-studio) for the full
model.

## The same analysis, multiple views

A publication report, a linked explorer, and a Three.js briefing all draw from
the Rio athlete notebook. Each view is an independent frontend project
connected to the notebook's data, computation, controls, and results.

<table width="100%">
  <tr>
    <td align="center">
      <a href="https://marimo-team.github.io/marimo-studio/examples/athletes/notebook/index.html"><strong>Notebook</strong></a><br>
      <a href="https://github.com/marimo-team/marimo"><code>Marimo</code></a> · <a href="https://github.com/python/cpython"><code>Python</code></a> · <a href="https://github.com/pola-rs/polars"><code>Polars</code></a><br>
      The notebook keeps the data, calculations, and controls used by every view.<br><br>
      <a href="https://marimo-team.github.io/marimo-studio/examples/athletes/notebook/index.html">
        <img src="apps/docs/public/screenshots/athletes-notebook.png" alt="Marimo notebook showing the athlete data transformation and table" width="100%">
      </a>
    </td>
  </tr>
</table>

<table width="100%">
  <tr>
    <td width="33%" valign="top">
      <a href="https://marimo-team.github.io/marimo-studio/examples/athletes/overview/index.html"><strong>Report</strong></a><br>
      <a href="https://github.com/whatwg/html"><code>Vanilla HTML</code></a><br>
      A report that summarizes the main numbers.<br><br>
      <a href="https://marimo-team.github.io/marimo-studio/examples/athletes/overview/index.html">
        <img src="apps/docs/public/screenshots/athletes-overview.png" alt="Athlete report showing totals for athletes, countries, sports, and medalists" width="100%">
      </a>
    </td>
    <td width="33%" valign="top">
      <a href="https://marimo-team.github.io/marimo-studio/examples/athletes/explorer/index.html"><strong>Explorer</strong></a><br>
      <a href="https://github.com/sveltejs/svelte"><code>Svelte</code></a> · <a href="https://github.com/uwdata/mosaic"><code>Mosaic</code></a><br>
      An interactive view for filtering and comparing athletes.<br><br>
      <a href="https://marimo-team.github.io/marimo-studio/examples/athletes/explorer/index.html">
        <img src="apps/docs/public/screenshots/athletes-explorer.png" alt="Athlete explorer with filters and a height and weight scatterplot" width="100%">
      </a>
    </td>
    <td width="33%" valign="top">
      <a href="https://marimo-team.github.io/marimo-studio/examples/athletes/field/index.html"><strong>Field briefing</strong></a><br>
      <a href="https://github.com/whatwg/html"><code>Vanilla HTML</code></a> · <a href="https://github.com/shower/shower"><code>Shower</code></a> · <a href="https://github.com/mrdoob/three.js"><code>Three.js</code></a><br>
      An interactive presentation of the athletes across sports.<br><br>
      <a href="https://marimo-team.github.io/marimo-studio/examples/athletes/field/index.html">
        <img src="apps/docs/public/screenshots/athletes-field.png" alt="Athlete field briefing showing Olympic athletes as points on a sphere" width="100%">
      </a>
    </td>
  </tr>
</table>

[Explore the notebook and its views.](https://marimo-team.github.io/marimo-studio/examples/athletes)

## Create your first view

Start with a saved notebook such as `analysis.py`:

```console
uvx marimo-studio view create dashboard --target analysis.py
uvx --with marimo-studio==0.1.0 marimo edit analysis.py --sandbox
```

The first command creates the view source beside the notebook. The second opens
marimo with three connected surfaces:

- **Notebook** for Python and reactive computation
- **Source** for the view's HTML, styles, and browser code
- **Preview** for the rendered view

Choose **Develop** to see all three. Saving Source rebuilds Preview, while a
failed build leaves the last successful view available.

![Notebook, view source, and Preview together in Develop](apps/docs/public/screenshots/studio-develop.png)

Studio calls each named frontend project a **view**. Add another view when the
same analysis needs a different layout, explanation, or interaction for another
purpose.

## Choose a frontend

The default view starts in one editable `index.html`. Keep styles and scripts
inline, or move them into directly referenced local CSS and JavaScript files as
the view grows. The starter places enabled cells that may display output,
including literal Markdown, in document order. This gives reports, dashboards,
and focused tools an editable first view immediately.

Choose React or Svelte when the view benefits from components and a larger
frontend source tree. Use the `marimo-studio/react:reveal` starter for a React
slide deck with one initial slide per enabled cell that may display output. Run
React, Reveal.js, and Svelte creation through `marimo-studio[deno]==0.1.0`. Once
configured, Studio derives the Deno requirement from the saved provider key for
`status`, view creation, source inspection and editing commands, `view build`,
`view export`, and `validate`.

Teams can connect another frontend build when an existing project should remain
the source of the view. The [frontend integration
reference](https://marimo-team.github.io/marimo-studio/reference/provider-api)
defines the small Python contract that creates, inspects, and builds that
source.

## Place notebook results in a view

View source can place a complete cell, one rendered Python object, or a
JSON-compatible value:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

All Python computation runs in the notebook. View source references notebook
results by name and controls where each result appears. Marimo continues to own
reactive execution, controls, widgets, and rich output rendering.

## Author with an agent

The package includes an Agent Skill and a code-mode Python API. People and
agents inspect the same notebook and view source, make revision-safe edits,
build, preview, and validate the rendered result.

Edits use the same source files and conflict protection. Read [Author with an
agent](https://marimo-team.github.io/marimo-studio/guide/coding-agents) for the
complete workflow.

## Run or publish

View source stays fixed while the notebook runs on a Python server or in a
browser worker. Use `marimo run` when the notebook needs Python packages, local
files, databases, or server credentials. Use browser execution when the notebook
and its data can run in Pyodide. A static export packages that browser runtime
and the view into a directory for HTTP hosting.

Read [Run or publish a
view](https://marimo-team.github.io/marimo-studio/guide/run-and-share) before
choosing where the notebook will execute.

## Documentation and support

Marimo Studio 0.1.0 supports Python 3.10 through 3.14 and Marimo 0.24.0. React,
Reveal.js, and Svelte authoring use the optional Deno 2.9.5 dependency.

- [Documentation](https://marimo-team.github.io/marimo-studio/) covers guided
  workflows and exact API contracts.
- [Troubleshooting](https://marimo-team.github.io/marimo-studio/guide/troubleshooting)
  starts from common symptoms and repair commands.
- [Issues](https://github.com/marimo-team/marimo-studio/issues) tracks public bug
  reports and support requests.
- [Security policy](SECURITY.md) defines the private vulnerability-reporting
  path.
- [Contributing](CONTRIBUTING.md) defines repository setup and review gates.

## License

Marimo Studio is licensed under the [Apache License 2.0](LICENSE).
