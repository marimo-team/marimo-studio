<p align="center">
  <a href="https://marimo-team.github.io/marimo-studio/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://marimo-team.github.io/marimo-studio/brand/marimo-studio-lockup-horizontal-dark.svg">
      <img alt="Marimo Studio" src="https://marimo-team.github.io/marimo-studio/brand/marimo-studio-lockup-horizontal-light.svg" width="620">
    </picture>
  </a>
</p>

<p align="center"><strong>Tune your notebook for every audience.</strong></p>

Marimo Studio turns one reactive, reproducible
[marimo](https://marimo.io/) notebook into custom web views for different
audiences. The notebook owns data access, transformations, metrics, controls,
and domain decisions. Each view owns page structure, styles, and browser logic
in ordinary HTML, CSS, and JavaScript files. People and coding agents can shape
the interface while the analytical logic continues to evolve in one place.

From a repository checkout, open the revenue forecast in Studio:

```console
uvx --with marimo-studio marimo edit examples/analysis.py --sandbox
```

Choose **Build** to work on the notebook and view together. Serve the finished
view with the same Marimo application:

```console
uvx --with marimo-studio marimo run examples/analysis.py --sandbox
```

The collection research example provides Corpus, Study, and Packet views over
one notebook session:

```console
uvx --with marimo-studio marimo edit examples/nga_collection.py --sandbox
uvx --with marimo-studio marimo run examples/nga_collection.py --sandbox
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
for multi-view authoring, browser integration, coding-agent workflows,
runtimes, and API contracts.
