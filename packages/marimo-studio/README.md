# Marimo Studio

Marimo Studio turns one [marimo](https://marimo.io/) notebook into reports,
apps, and presentations. Keep data, computation, and controls in Python.
Shape each view for its audience, by hand or with a coding agent.

Marimo Studio 0.1 is experimental. Pin Studio and third-party view providers in
saved projects.

## Get started

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Add a displayable cell, then click **Add view** in the Studio toolbar. Save the
notebook if prompted and choose a name and starter. Notebook and Preview open
side by side. Use the source action to edit the view's files, or work through
Marimo's agent sidebar.

Saving view source rebuilds Preview. A failed build retains the last successful
view. Follow the [quickstart](https://marimo-team.github.io/marimo-studio/guide/getting-started)
for a complete first view. [uv](https://docs.astral.sh/uv/) supplies `uvx` and
resolves the notebook's declared dependencies with `--sandbox`.

## For agents

Read the version-matched briefing shipped with Studio:

```console
uvx --with marimo-studio agent-plugins read marimo-studio
```

From the notebook's Python environment:

```python
import marimo_studio.agent

help(marimo_studio.agent)
```

The briefing covers inspecting, creating, editing, building, and verifying
views. Follow the [agent guide](https://marimo-team.github.io/marimo-studio/guide/coding-agents)
to connect your agent and work with optional Marimo Lens feedback.

## Run or export a view

Serve a live **Python** app, run Python in the **Browser** with Pyodide, or publish
**Prepared** results as a static site. Browser delivery includes notebook source.
Prepared delivery includes the exported results and finite input states.

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
