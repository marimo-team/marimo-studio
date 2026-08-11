<p align="center">
  <a href="https://marimo-team.github.io/marimo-studio/">
    <img alt="A Marimo notebook and a custom operations view in Marimo Studio" src="https://marimo-team.github.io/marimo-studio/og.png" width="1100">
  </a>
</p>

<p align="center"><strong>Tune your notebook for every audience.</strong></p>

Marimo Studio turns one reactive, reproducible
[marimo](https://marimo.io/) notebook into custom web views for different
audiences. The notebook owns data access, transformations, metrics, controls,
and domain decisions. Each view owns page structure, styles, and browser logic
in ordinary HTML, CSS, and JavaScript files. Coding agents can inspect and edit
those files while the analytical logic continues to evolve in one place.

From a repository checkout, open the revenue forecast in Studio:

```console
uvx --with marimo-studio marimo edit examples/analysis.py --sandbox
```

Choose **Build** to work on the notebook and view together. Serve the finished
view with the same Marimo application:

```console
uvx --with marimo-studio marimo run examples/analysis.py --sandbox
```

Studio runs inside Marimo and uses its kernels, sessions, authentication,
routing, controls, and output renderers. Select complete cell output, one
Python object rendered by Marimo, or a JSON-compatible browser value:

```html
<marimo-cell name="controls"></marimo-cell>
<marimo-output value="revenue_table"></marimo-output>
<time mo-value="report.updated_at"></time>
```

Read the [Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/)
to create views, project notebook results, automate view authoring, and choose a
runtime.

## License

Marimo Studio is licensed under the
[Apache License 2.0](https://github.com/marimo-team/marimo-studio/blob/main/LICENSE).
