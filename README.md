<p align="center">
  <a href="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/marimo-studio.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/marimo-studio.svg"></a>
</p>

<p align="center"><strong>Tune your notebook for every audience.</strong></p>

Marimo Studio turns one reactive, reproducible
[marimo](https://marimo.io/) notebook into custom web views for different
audiences. The notebook owns data access, transformations, metrics, controls,
and domain decisions. Each view gives an audience its own layout and
interaction model.

## What you can do

- **[Create several views](https://marimo-team.github.io/marimo-studio/guide/views).**
  Give each audience its own route, structure, language, and interaction while
  reusing one notebook.
- **[Use any frontend stack](https://marimo-team.github.io/marimo-studio/guide/authoring-options).**
  Use the source files and tooling that fit each view.
- **[Keep results interactive](https://marimo-team.github.io/marimo-studio/guide/notebook-results).**
  Place reactive notebook results inside custom layouts.
- **[Build beside the notebook](https://marimo-team.github.io/marimo-studio/guide/live-authoring).**
  Move between notebook, source, and preview while the kernel stays active.
- **[Run and share](https://marimo-team.github.io/marimo-studio/guide/run-and-share).**
  Serve views from Python, run them in the browser, or export them for static
  hosting.

## Try Studio

From a repository checkout, open the National Gallery of Art notebook and its
three views:

```console
make install
uv run --with polars --with pyobservablejs marimo edit examples/nga.py
```

Choose **Develop** to work on the notebook and selected view together. Use the
view menu to move among its three frontends.

Run the same notebook as an application:

```console
uv run --with polars --with pyobservablejs marimo run examples/nga.py
```

## Documentation

Read the [Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/)
for setup, frontend authoring, notebook results, live editing, automation, and
deployment.

## License

Marimo Studio is licensed under the [Apache License 2.0](LICENSE).
