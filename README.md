<p align="center">
  <a href="https://marimo-team.github.io/marimo-studio/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://marimo-team.github.io/marimo-studio/brand/marimo-studio-lockup-horizontal-dark.svg">
      <img alt="Marimo Studio" src="https://marimo-team.github.io/marimo-studio/brand/marimo-studio-lockup-horizontal-light.svg" width="360">
    </picture>
  </a>
</p>

<p align="center">
  <a href="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/marimo-studio.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="Python 3.10 through 3.14" src="https://img.shields.io/badge/python-3.10%E2%80%933.14-blue.svg"></a>
</p>

Marimo Studio builds custom reports, apps, and presentations from one
[marimo](https://marimo.io/) notebook. Keep the analysis in Python, then shape
each view with HTML, [React](https://react.dev/),
[Svelte](https://svelte.dev/), or the browser libraries your work needs.

> **Experimental:** Marimo Studio is changing rapidly.

## Examples

One notebook supplies the data and calculations for three views, each with its
own frontend and interaction model.

### [Notebook](https://marimo-team.github.io/marimo-studio/examples/athletes/notebook/index.html)

[`marimo`](https://github.com/marimo-team/marimo) ·
[`Python`](https://github.com/python/cpython) ·
[`Polars`](https://github.com/pola-rs/polars)

Load the Rio roster, derive age and medal counts, and inspect the data used by
every view.

[![Marimo notebook loading and transforming the Rio athlete records](apps/docs/public/screenshots/athletes-notebook.png)](https://marimo-team.github.io/marimo-studio/examples/athletes/notebook/index.html)

### [Publication report](https://marimo-team.github.io/marimo-studio/examples/athletes/overview/index.html)

[`Vanilla HTML`](https://github.com/whatwg/html)

Summarize 11,538 athletes, 207 delegations, 28 sports, and 1,857 medalists.

[![Athlete report showing totals for athletes, delegations, sports, and medalists](apps/docs/public/screenshots/athletes-overview.png)](https://marimo-team.github.io/marimo-studio/examples/athletes/overview/index.html)

### [Linked explorer](https://marimo-team.github.io/marimo-studio/examples/athletes/explorer/index.html)

[`Svelte`](https://github.com/sveltejs/svelte) ·
[`Mosaic`](https://github.com/uwdata/mosaic)

Filter by sport or sex, search by name, and brush charts to update the roster,
distributions, and totals together.

[![Athlete explorer with roster filters and a linked height and weight plot](apps/docs/public/screenshots/athletes-explorer.png)](https://marimo-team.github.io/marimo-studio/examples/athletes/explorer/index.html)

### [Interactive briefing](https://marimo-team.github.io/marimo-studio/examples/athletes/field/index.html)

[`Vanilla HTML`](https://github.com/whatwg/html) ·
[`Shower`](https://github.com/shower/shower) ·
[`Three.js`](https://github.com/mrdoob/three.js)

Move through the roster, sports, medalists, and body profiles in a four-chapter
presentation built from one point per athlete.

[![Athlete briefing showing the Olympic roster as an interactive point field](apps/docs/public/screenshots/athletes-field.png)](https://marimo-team.github.io/marimo-studio/examples/athletes/field/index.html)

[Explore the notebook and every live view.](https://marimo-team.github.io/marimo-studio/examples/athletes)

## Quickstart

Open a notebook in an environment that contains Studio:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

`uvx` is [uv](https://docs.astral.sh/uv/)'s temporary command runner. It creates
an isolated Python environment for this invocation.

Add a cell such as `mo.md("## Revenue is on target")`, then save the notebook.
Studio opens the first-view screen. Choose **HTML document** and click **Create
dashboard**. The generated view places displayable notebook cells
inside a frontend document.

Studio connects three surfaces:

- **Notebook** for Python and reactive computation
- **Source** for the view project's HTML, styles, and browser code
- **Preview** for the current artifact and notebook runtime

**Develop** opens Notebook and Preview in an equal split. Click **Source** in the
toolbar to add the view editor beneath Notebook.

Saving Source rebuilds Preview. A failed build reports the source problem and
keeps the current artifact available.

![Notebook, view source, and Preview in a custom layout](apps/docs/public/screenshots/studio-develop.png)

For terminal-first setup with an existing saved notebook, run:

```console
uvx marimo-studio view create dashboard --target analysis.py
```

## Build and run

```text
notebook
  -> named view project
  -> validated artifact
  -> Python, Browser, or Prepared runtime
  -> rendered view
```

One notebook can publish several named views, each with its own source, build,
and runtime. Choose Python for server-backed views, Browser for views that run
with [Pyodide](https://pyodide.org/) in the browser, or Prepared for static
publishing from precomputed results. Prepared exports keep the Python notebook
source on the build machine.

## Learn and operate

- [Start here](https://marimo-team.github.io/marimo-studio/guide/)
- [Work in Studio](https://marimo-team.github.io/marimo-studio/guide/work-in-studio)
- [Place notebook results](https://marimo-team.github.io/marimo-studio/guide/notebook-results)
- [Run or export a view](https://marimo-team.github.io/marimo-studio/guide/run-and-share)
- [Reference](https://marimo-team.github.io/marimo-studio/reference/)
- [Troubleshooting](https://marimo-team.github.io/marimo-studio/guide/troubleshooting)
- [Security](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

## License

Marimo Studio is licensed under the [Apache License 2.0](LICENSE).
