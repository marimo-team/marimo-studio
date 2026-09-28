# marimo-studio

`marimo-studio` turns one [marimo](https://marimo.io/) notebook into reports,
apps, and presentations. Keep data, computation, and controls in Python.
Shape each view for its audience, by hand or with a coding agent. Each view is
its own frontend project, and every result it shows traces back to the notebook
cell that computed it.

![Four example notebooks, each heading a column of its views](https://marimo-team.github.io/marimo-studio/showcase/marimo-studio-wall-light.webp)

Studio is experimental. Pin `marimo-studio` and third-party view providers in
saved projects.

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
`uvx`. Follow the [agent guide](https://marimo-team.github.io/marimo-studio/guide/coding-agents)
for pairing with a running notebook and pointing at results with
[Lens](https://marimo-team.github.io/marimo-lens/).

## Start by hand

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Add a cell that displays a result, then click **Add view** in the Studio
toolbar. Save the notebook if prompted and choose a name and starter. Notebook
and Preview open side by side. Saving view source rebuilds Preview, and a
failed build keeps the last successful view. Follow
[Getting started](https://marimo-team.github.io/marimo-studio/guide/getting-started)
for a complete first view.

## Run or export a view

Serve a live **Python** app, run Python in the **Browser** with Pyodide, or publish
**Prepared** results as a static site. A Browser export includes notebook source.
A Prepared export includes the exported results and finite input states and
keeps notebook source on the machine that runs the export.

[Run or export a view](https://marimo-team.github.io/marimo-studio/guide/run-and-share)
explains the delivery choice and what visitors receive.

## Documentation

[Guide](https://marimo-team.github.io/marimo-studio/guide/) ·
[Examples](https://marimo-team.github.io/marimo-studio/examples/) ·
[Reference](https://marimo-team.github.io/marimo-studio/reference/) ·
[Compatibility](https://marimo-team.github.io/marimo-studio/reference/compatibility) ·
[Troubleshooting](https://marimo-team.github.io/marimo-studio/guide/troubleshooting)

Report bugs through [GitHub Issues](https://github.com/marimo-team/marimo-studio/issues).
See the [security policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md)
for private reports.

## License

[Apache License 2.0](https://github.com/marimo-team/marimo-studio/blob/main/LICENSE).
