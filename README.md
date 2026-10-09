<p align="center">
  <a href="https://marimo-team.github.io/marimo-studio/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://marimo-team.github.io/marimo-studio/brand/marimo-studio-lockup-horizontal-dark.svg">
      <img alt="marimo-studio" src="https://marimo-team.github.io/marimo-studio/brand/marimo-studio-lockup-horizontal-light.svg" width="360">
    </picture>
  </a>
</p>

<p align="center">
  <a href="https://marimo-team.github.io/marimo-studio/examples/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="apps/docs/public/showcase/marimo-studio-wall-dark.webp">
      <img alt="Four example notebooks, each heading a column of its views" src="apps/docs/public/showcase/marimo-studio-wall-light.webp" width="100%">
    </picture>
  </a>
</p>

<p align="center">
  <b>One reactive notebook. Many views.</b><br>
  Turn a <a href="https://marimo.io/">marimo</a> notebook into apps, presentations, articles, and PDF reports, by hand or with a coding agent.
</p>

<p align="center">
  <a href="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/marimo-team/marimo-studio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/marimo-studio.svg"></a>
  <a href="https://pypi.org/project/marimo-studio/"><img alt="Python 3.10 through 3.14" src="https://img.shields.io/badge/python-3.10%E2%80%933.14-blue.svg"></a>
</p>

Studio keeps data, computation, and controls in the notebook and gives each
audience its own view, such as a dashboard, a slide deck, an article, or a PDF
report. A view places the notebook's cells, outputs, and values by name. Web
pages keep them live, so changing an input updates every result that depends
on it, and Typst documents render again with the new values. Every result a
view shows traces back to the notebook cell that computed it.

> [!NOTE]
> Studio is experimental and changing rapidly. Pin `marimo-studio` in saved
> projects.

## Start with a coding agent

Paste this request into Claude Code, Codex, or another terminal agent:

```text
Run `uvx --with marimo-studio agent-plugins read marimo-studio` and create
a scrollytelling report and a slide deck explaining calculus basics.
```

The agent reads the instructions Studio ships for coding agents, starts a
notebook with Studio in your browser, and writes the calculus in Python cells.
It then builds both views and shows them beside the notebook. Change the topic,
or name a notebook you already have. [uv](https://docs.astral.sh/uv/) supplies
`uvx`.

[Author with a coding agent](https://marimo-team.github.io/marimo-studio/guide/coding-agents)
covers pairing with a running notebook and pointing at results with
[Lens](https://marimo-team.github.io/marimo-lens/).

## Start by hand

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox --watch
```

Add a cell that displays a result, then click **Add view** in the Studio
toolbar. Save the notebook if prompted, choose **HTML document**, and create
the view. Notebook and Preview open side by side. Saving view source rebuilds
Preview, and a failed build keeps the last successful view.

![Notebook, Preview, and view source in Studio](apps/docs/public/screenshots/studio-develop.png)

[Getting started](https://marimo-team.github.io/marimo-studio/guide/getting-started)
walks through a complete first view.

## Examples

Each example notebook backs several views, each built with its own document
technology.

- [Quadratic programs](https://marimo-team.github.io/marimo-studio/examples/quadratic-programs): a Reveal.js lecture, an HTML
  explainer, a Svelte and D3 lab, and a Typst PDF report.
- [Rio 2016 athletes](https://marimo-team.github.io/marimo-studio/examples/athletes): an HTML overview, a Mosaic explorer, a
  Three.js presentation, and a Quarto paper typeset with KaTeX.
- [Earthquake watch](https://marimo-team.github.io/marimo-studio/examples/earthquakes): an Observable Plot story, a MapLibre
  operations map, a Reveal.js briefing, and a Quarto bulletin.
- [Building occupancy](https://marimo-team.github.io/marimo-studio/examples/occupancy): a Notebook Kit monitor, a Recharts
  model review, and a pdfcn PDF report.

## Run or export a view

Serve the notebook's views as a live **Python** app:

```console
uvx --with marimo-studio marimo run analysis.py --sandbox
```

Export the `report` view with **Prepared** results as a static site:

```console
uvx marimo-studio view export report --target analysis.py --output dist/report
```

A Prepared export publishes the exported results and finite input states and
keeps notebook source on the machine that runs the export. Views can also run
Python in the visitor's **Browser**.
[Run or export a view](https://marimo-team.github.io/marimo-studio/guide/run-and-share)
compares what visitors receive.

## Documentation

[Guide](https://marimo-team.github.io/marimo-studio/guide/) ·
[Examples](https://marimo-team.github.io/marimo-studio/examples/) ·
[Reference](https://marimo-team.github.io/marimo-studio/reference/) ·
[Troubleshooting](https://marimo-team.github.io/marimo-studio/guide/troubleshooting) ·
[Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

## License

[Apache License 2.0](LICENSE).
