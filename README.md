<p align="center">
  <a href="https://marimo-team.github.io/marimo-studio/">
    <img alt="A Marimo notebook and a custom operations view in Marimo Studio" src="https://marimo-team.github.io/marimo-studio/og.png" width="1100">
  </a>
</p>

<p align="center">
  <a href="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/marimo-studio.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/marimo-studio.svg"></a>
</p>

<p align="center"><strong>Tune your notebook for every audience.</strong></p>

Marimo Studio turns one reactive, reproducible
[marimo](https://marimo.io/) notebook into custom web views for different
audiences. The notebook owns data access, transformations, metrics, controls,
and domain decisions. Each view owns page structure, styles, and browser logic
in ordinary HTML, CSS, and JavaScript files. People and coding agents can shape
the interface while the analytical logic continues to evolve in one place.

Studio runs inside Marimo. `marimo edit` opens the notebook and view together.
`marimo run` serves finished views with Marimo's kernels, sessions,
authentication, routing, controls, and output renderers.

## Try Studio

From a repository checkout, open the revenue forecast in the Studio editor:

```console
uvx --with marimo-studio marimo edit examples/analysis.py --sandbox
```

Choose **Build** to work on the notebook and view together. Run the same
notebook as an application at its default Studio view:

```console
uvx --with marimo-studio marimo run examples/analysis.py --sandbox
```

## Create your first view

Add a view to an existing notebook, then open it through Marimo:

```console
uvx marimo-studio view add analysis.py
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

The new `dashboard` view begins with the notebook's cells in source order.
The default view opens at `/`. A named view such as `executive` opens at
`/executive/` in the same Marimo application.

## One notebook, several views

Create one view for each audience or task while keeping the analytical graph
in the notebook:

| View         | Reader job                           | Content                                      |
| ------------ | ------------------------------------ | -------------------------------------------- |
| `dashboard`  | Explore and adjust the current model | Controls, detailed measures, plots, tables   |
| `operations` | Find conditions that require action  | Exceptions, thresholds, owners, next steps   |
| `executive`  | Review the outcome and decision      | Headline measures, risks, and recommendation |

The notebook owns data access, transformations, calculations, reactive
dependencies, controls, and native Marimo components. Each view owns its page
structure, wording, styles, modules, assets, and route. Stylesheets and browser
modules stay in view files, keeping notebook cells focused on analysis.
Updating a notebook definition updates every view that projects the affected
result.

## Project notebook results

Studio connects a notebook to an authored web document through three
primitives:

| Need                                               | Projection                    |
| -------------------------------------------------- | ----------------------------- |
| Include everything a cell produced                 | `<marimo-cell name="...">`    |
| Render one Python object through Marimo            | `<marimo-output value="...">` |
| Read a JSON-compatible value in HTML or JavaScript | `mo-value="..."`              |

```html
<marimo-cell name="controls"></marimo-cell>
<marimo-output value="revenue_table"></marimo-output>
<time mo-value="report.updated_at"></time>
```

`<marimo-cell>` includes complete cell output, including output appended with
`mo.output.append(...)`. `<marimo-output>` formats a selected Python object as
native Marimo output. `mo-value` renders a JSON-compatible value in an HTML
element and exposes its typed snapshot to browser code.

[Use notebook results](https://marimo-team.github.io/marimo-studio/guide/notebook-results)
develops each primitive with working examples.

## Use the web platform

A view is a complete HTML document. Add stylesheets, JavaScript modules,
browser APIs, SVG, Canvas, Web Components, images, fonts, and existing browser
libraries through ordinary relative files. Studio keeps native Marimo
controls, plots, tables, downloads, and anywidgets connected to the selected
runtime.

[Use HTML, CSS, and JavaScript](https://marimo-team.github.io/marimo-studio/guide/web-platform)
covers browser behavior, assets, loading states, and the built-in utility
classes.

## Work with people and coding agents

View source stays in ordinary web files beside the notebook. A coding agent can
inspect the saved notebook graph, create a view, bind a stable cell name, edit
the view files, and validate every projection. Metric definitions,
transformations, and domain rules remain visible in notebook cells for review.

[Work with coding agents](https://marimo-team.github.io/marimo-studio/guide/coding-agents)
documents the inspect, create, edit, and check loop.

## Choose a runtime

Use the Server runtime when the notebook needs a full Python environment,
local resources, databases, or credentials. Use the WebAssembly runtime when
the notebook and its dependencies run in Pyodide.

Export one WebAssembly view for a static host:

```console
uvx marimo-studio export analysis.py --view executive --output dist/executive
python -m http.server --directory dist/executive
```

The static export contains the notebook source. Review the notebook and its
data access before publishing the generated directory.

Marimo Studio supports Python 3.10 or newer and Marimo 0.23.16 or newer.

## Documentation

Read the [Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/)
to create views, project notebook results, work with coding agents, and choose
a runtime.

## License

Marimo Studio is licensed under the [Apache License 2.0](LICENSE).
