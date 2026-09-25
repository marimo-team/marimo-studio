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

Marimo Studio turns one [marimo](https://marimo.io/) notebook into reports,
apps, and presentations. Keep data, computation, and controls in Python.
Shape each view for its audience, by hand or with a coding agent.

> **Experimental:** Marimo Studio is changing rapidly.

[![Notebook, view source, and Preview in Studio](apps/docs/public/screenshots/studio-develop.png)](https://marimo-team.github.io/marimo-studio/)

## Get started

Open a notebook with Studio installed:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Add a displayable cell, then click **Add view** in the Studio toolbar. Save the
notebook if prompted, choose **HTML document**, and create the view. Notebook
and Preview open side by side. The source action opens the view's files, and
Marimo's agent sidebar stays available.

Saving view source rebuilds Preview. Notebook controls keep their reactive
behavior, and a failed build retains the last successful view.

Follow the [quickstart](https://marimo-team.github.io/marimo-studio/guide/getting-started)
for a complete first view. [uv](https://docs.astral.sh/uv/) supplies `uvx` and
resolves the notebook's declared dependencies with `--sandbox`.

## Example: Rio 2016 athletes

The [Rio 2016 notebook](https://marimo-team.github.io/marimo-studio/examples/athletes/notebook/index.html)
supplies one analysis to three interfaces:

| View                                                                                                    | Explore                                                      |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [Publication report](https://marimo-team.github.io/marimo-studio/examples/athletes/overview/index.html) | Roster totals, delegations, sports, and medalists            |
| [Linked explorer](https://marimo-team.github.io/marimo-studio/examples/athletes/explorer/index.html)    | Filter the roster and brush linked charts                    |
| [Interactive briefing](https://marimo-team.github.io/marimo-studio/examples/athletes/field/index.html)  | Move through the athlete data in a four-chapter presentation |

Use HTML, React, Svelte, or Observable Notebook Kit. Each view owns its source
and browser dependencies. [Explore all examples](https://marimo-team.github.io/marimo-studio/examples/).

## For agents

Read the version-matched briefing shipped with Studio:

```console
uvx --with marimo-studio agent-plugins read marimo-studio
```

From the notebook's Python environment:

```python
import marimo_studio.agent

print(help(marimo_studio.agent))
```

The briefing covers inspecting the notebook, creating and editing a view,
building it, and checking the rendered result. The
[agent guide](https://marimo-team.github.io/marimo-studio/guide/coding-agents)
explains connection and optional visual feedback with Marimo Lens.

## Run or export a view

Use a live **Python** server, execute Python in the **Browser**, or export
**Prepared** results as a static site. Prepared delivery publishes the exported
results and input states while keeping Python source on the build machine.

[Run or export a view](https://marimo-team.github.io/marimo-studio/guide/run-and-share)
covers the delivery choice and what visitors receive.

## Documentation

[Guide](https://marimo-team.github.io/marimo-studio/guide/) ·
[Reference](https://marimo-team.github.io/marimo-studio/reference/) ·
[Troubleshooting](https://marimo-team.github.io/marimo-studio/guide/troubleshooting) ·
[Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

## License

[Apache License 2.0](LICENSE).
