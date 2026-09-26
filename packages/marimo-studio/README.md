# marimo-studio

`marimo-studio` turns one [marimo](https://marimo.io/) notebook into reports,
apps, and presentations. Keep data, computation, and controls in Python.
Shape each view for its audience, by hand or with a coding agent.

Studio is experimental. Pin `marimo-studio` and third-party view providers in
saved projects.

## Get started

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Add a displayable cell, then click **Add view** in the Studio toolbar. Save the
notebook if prompted and choose a name and starter. Notebook and Preview open
side by side. Use the source action to edit the view's files, or work through
marimo's agent sidebar.

Saving view source rebuilds Preview. A failed build retains the last successful
view. Follow the [quickstart](https://marimo-team.github.io/marimo-studio/guide/getting-started)
for a complete first view. [uv](https://docs.astral.sh/uv/) supplies `uvx` and
resolves the notebook's declared dependencies with `--sandbox`.

## Build a view with a coding agent

Give a terminal agent such as Claude Code or Codex one instruction:

```console
claude 'Follow `uvx --with marimo-studio agent-plugins read marimo-studio`
to build a briefing view of analysis.py that leads with the headline results.'
```

`agent-plugins read` prints the briefing Studio ships for coding agents through
[Agent Plugins](https://github.com/peter-gy/agent-plugins). It tells the agent
how to pair with your running notebook, or start one, then create, build, and
show the view. Follow the [agent guide](https://marimo-team.github.io/marimo-studio/guide/coding-agents)
for request guidance and visual feedback with
[Lens](https://marimo-team.github.io/marimo-lens/).

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
