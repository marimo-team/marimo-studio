---
title: Author with a coding agent
description: Give an agent Studio's installed instructions, ask for a view, and review its rendered result.
---

# Author with a coding agent

A coding agent can inspect a notebook, create a view, edit its source, and
verify the result in a browser. Studio ships the instructions and Python API
with the package, so the agent works from your installed version.

## Give the agent its briefing

In the notebook's Python environment, the agent reads:

```python
import agent_plugins as ap

print(ap.read("marimo-studio"))
```

Python help includes the same briefing alongside the API:

```python
import marimo_studio.agent

print(help(marimo_studio.agent))
```

For a terminal agent, start with:

```console
uvx --with marimo-studio agent-plugins read marimo-studio
```

That command reads an isolated installation. When the agent connects to a live
notebook, it reads the briefing from the notebook's environment. Reading the
briefing is passive. It leaves notebook execution and the selected view alone.

## Ask for a view

[Open your notebook in Studio](getting-started.md), then use Marimo's AI sidebar
in **Code Mode (beta)** or connect your agent through **Settings → Pair with an
agent**. Code mode lets the agent run Python in the live notebook kernel.

Give the agent an audience, a task, and a result to check:

> Read the installed marimo-studio briefing. Create a view named `briefing`
> for a quarterly review. Use the notebook's existing measures and controls.
> Lead with the headline results, then show the evidence behind them. Verify
> the view at desktop and phone widths and check that changing a control
> updates its dependent results.

The agent inspects the notebook and available starters, reads the view's
`AGENTS.md`, then edits, builds, and shows the view. Review the result in
Preview. Keep shared calculations in the notebook and audience-specific layout
and wording in the view. Record lasting visual decisions in the project's
`DESIGN.md`.

## Inspect and verify

For agent authors and integrations, the live API begins with the current
workspace. Run this in one code-mode execution:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
notebook = await workspace.inspect_notebook()
print(notebook.notebook.named_cells())
print(await workspace.starters())
```

`inspect_notebook()` reads saved source. Its optional runtime inspection runs a
separate process. Live kernel values, the published build, and the displayed
browser result are separate evidence.

After authoring and building `briefing`, show it in a new code-mode execution:

```python
import marimo_studio.agent as studio_agent

view = studio_agent.current_workspace().view("briefing")
await view.show()
print(await view.preview_url(runtime="server"))
```

Reacquire workspace and view handles in each execution. Finish the execution
before an external browser tool waits for notebook results. After changing
Python, run the changed cells in the live notebook.

Check source and build freshness with `view.inspect()`. A failed build retains
the last working artifact, so a visible page alone does not prove the edit was
published. In the browser, wait for
`html[data-marimo-studio-state="ready"]`, inspect wide and narrow layouts, and
exercise controls through to their dependent results. Verify exports in the
[delivery runtime](run-and-share.md) visitors will use.

The [Python API](../reference/python-api.md#marimo-studio-agent) defines methods
and records. The installed skill supplies the complete authoring workflow and
references for source edits, projections, verification, and delivery:

```python
import marimo_studio.agent as studio_agent

print(studio_agent.skill().file("references/verification.md").read_text())
```

## Select results with Marimo Lens {#point-to-a-result-with-marimo-lens}

[Marimo Lens](https://marimo-team.github.io/marimo-lens/) lets you select a
rendered result and attach a note. The agent receives the image and the
notebook context behind that selection. Install Lens in the notebook's Python
environment:

```console
uv pip install "marimo-studio[lens]"
```

The `lens` extra selects a Lens release that matches the installed Studio. For
sandboxed notebooks, also declare `marimo-studio[lens]` in the script's
dependencies. Restart a running notebook after installing or upgrading Lens.

When the notebook imports no Lens of its own, Marimo mounts one in the notebook.
The development preview reuses that same Lens, so the Notebook pane and the
preview each show a dock, and selections from either one reach the agent
together. Select a result, add a note, and ask:

> Use Lens to address my current selection in this Studio view.

Native projections carry their producing context automatically. For custom
charts or authored page regions, [connect the rendered result to its
inputs](../reference/projections.md#trace-custom-javascript-rendering). Lens's
[agent guide](https://marimo-team.github.io/marimo-lens/agents) owns the selection
and feedback workflow.
