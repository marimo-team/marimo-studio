---
title: Author with a coding agent
description: Ask a coding agent for a notebook and its views, see how the agent works in the live notebook, and review its work in Preview and with Lens.
---

# Author with a coding agent

A coding agent can turn a request such as "a slide deck and a scrollytelling
report explaining calculus" into a notebook and its views. Studio ships the
instructions the agent follows inside the `marimo-studio` package, and gives
the agent a Python API in the live notebook to create, build, and show views.
You review each result in Preview and point at what should change with
[Lens](lens.md).

## How an agent works with Studio

1. **It reads Studio's instructions.**
   [Agent Plugins](https://github.com/peter-gy/agent-plugins) prints the
   instructions that ship inside the `marimo-studio` package.
2. **It connects to the live notebook.** A terminal agent pairs with the
   running notebook through [`marimo pair`](https://marimo.io/pair). An agent
   in marimo's AI sidebar already runs there in **Code Mode (beta)**. Either
   way, the agent runs Python in the notebook's
   [session](../reference/glossary.md#session).
3. **It writes Python in the notebook and presentation in the view.** Data and
   computation go into notebook cells. Layout, wording, and page code go into
   the [view project](../reference/glossary.md#view-project), following its
   `AGENTS.md`, and its `DESIGN.md` when the view has one.
4. **It builds and shows the view.** The agent builds the view, checks the
   names it places, and selects the view in your Studio tab, so Preview shows
   what it made.
5. **It takes your feedback.** You review the view in Preview and select the
   parts that should change with Lens. When a selection shows a notebook
   result, the agent receives it with the notebook cells behind it.

## Ask for a view

Paste a request into a terminal agent such as Claude Code or Codex:

```text
Run `uvx --with marimo-studio agent-plugins read marimo-studio` and create
a scrollytelling report and a slide deck explaining calculus basics.
```

The first sentence makes the agent read the instructions, and
[uv](https://docs.astral.sh/uv/) supplies `uvx`. The agent then starts a
notebook with Studio, writes the analysis in Python cells, creates and builds
each view, and shows it in Preview beside the notebook.

Name a notebook you already have to build on its analysis:

```text
Run `uvx --with marimo-studio agent-plugins read marimo-studio` and build
a Typst report of analysis.py that leads with the headline results.
```

`marimo pair` finds local notebooks started with `--no-token`, and the agent
starts a stopped notebook that way. For a notebook started with a token, give
the agent its URL and a file that holds the token. In marimo's AI sidebar,
switch to **Code Mode (beta)** and ask for the view directly.

## Write a good request

Name the audience, the task, and something to check:

> Create a view named `briefing` for a quarterly review. Use the notebook's
> existing measures and controls. Lead with the headline results, then show
> the evidence behind them. Check the view at desktop and phone widths, and
> check that changing a control updates its results.

Review the result in Preview. Python belongs in the notebook, and layout,
wording, and page code belong in the view, as
[Python in the notebook, presentation in the view](../what-is-studio.md#python-in-the-notebook-presentation-in-the-view)
describes. Ask the agent to record lasting decisions, such as audience and
visual direction, in the view's `DESIGN.md`.

The agent reads each view's `AGENTS.md` before it edits the view. The
[Python API](../reference/python-api.md#marimo-studio-agent) lists the
methods it uses to inspect the notebook, build views, and show them.

## Point at what to change

Words like "the dip in that chart" leave the agent guessing which cell and
which value you mean. [Select results with Lens](lens.md) lets you select the
dip itself, in a page or inside a PDF, and add a note. The agent receives the
selection with the cell that computed it and the place in the view that shows
it, so it changes the notebook when the data is wrong and the view when the
presentation is.
