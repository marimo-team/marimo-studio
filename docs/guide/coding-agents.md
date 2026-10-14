---
title: Author with a coding agent
description: Ask a coding agent for a view, review the result in Preview, and point at results with Lens.
---

# Author with a coding agent

Studio ships instructions for coding agents inside the `marimo-studio`
package. An agent that reads them can write a notebook, create views in any
format, build them, and check the result in Preview.

## Ask for a view

Paste a request into a terminal agent such as Claude Code or Codex:

```text
Run `uvx --with marimo-studio agent-plugins read marimo-studio` and create
a scrollytelling report and a slide deck explaining calculus basics.
```

The first sentence makes the agent read the instructions.
[Agent Plugins](https://github.com/peter-gy/agent-plugins) prints the
instructions a Python package ships for agents, and
[uv](https://docs.astral.sh/uv/) supplies `uvx`. The agent then starts a
notebook with Studio, writes the analysis in Python cells, creates and builds
each view, and shows it in Preview beside the notebook.

Name a notebook you already have to build on its analysis:

```text
Run `uvx --with marimo-studio agent-plugins read marimo-studio` and build
a Typst report of analysis.py that leads with the headline results.
```

The agent runs code in the live notebook through
[`marimo pair`](https://marimo.io/pair). It finds local notebooks started with
`--no-token`, and starts a stopped notebook that way. For a notebook started
with a token, give the agent its URL and a file that holds the token.

In marimo's AI sidebar the agent already runs inside the notebook. Switch to
**Code Mode (beta)** and ask for the view directly.

## Write a good request

Name the audience, the task, and something to check:

> Create a view named `briefing` for a quarterly review. Use the notebook's
> existing measures and controls. Lead with the headline results, then show
> the evidence behind them. Check the view at desktop and phone widths, and
> check that changing a control updates its results.

Review the result in Preview. Shared calculations belong in the notebook, and
layout and wording belong in the view. Ask the agent to record lasting
decisions, such as audience and visual direction, in the view's `DESIGN.md`.

The agent reads each view's `AGENTS.md` before it edits the view. The
[Python API](../reference/python-api.md#marimo-studio-agent) lists the
methods it uses to inspect the notebook, build views, and show them.

## Select results with Lens

[Lens](https://marimo-team.github.io/marimo-lens/) lets you select part of a
rendered view and attach a note. The agent receives an image of the
selection, your note, and the notebook cells behind it, so it can tell
whether a change belongs in the view or in the notebook.

Install Lens in the notebook's Python environment, and restart a running
notebook afterwards:

```console
uv pip install "marimo-studio[lens]"
```

For a sandboxed notebook, also add `marimo-studio[lens]` to the script's
dependencies. Notebook and Preview then each show a Lens dock, and
selections from both reach the agent. Select a result, add a note, and ask:

> Use Lens to address my current selection in this Studio view.

Cells, outputs, and values carry their notebook context automatically. For a
chart that page code draws itself,
[connect it to its inputs](../reference/projections.md#trace-custom-javascript-rendering).
