---
layout: home
title: marimo-studio
titleTemplate: false
description: Compose the cells, outputs, and values of a marimo notebook into any document, from web pages and slide decks to typeset papers.

hero:
  text: Turn your marimo notebook into any document
  tagline: Use your notebook's outputs as building blocks. Place a chart, a table, or a single number in a web page, a slide deck, or a paper, and keep all of your Python in the notebook.
  actions:
    - theme: brand
      text: What is Studio?
      link: ./what-is-studio
    - theme: alt
      text: Get started
      link: ./guide/getting-started
    - theme: alt
      text: Examples
      link: ./examples/

features:
  - icon:
      src: /icons/panels-top-left.svg
      alt: Notebook results
      width: "24"
      height: "24"
    title: Building blocks
    details: Place a whole cell, one chart, or a single number wherever you need it. Each one traces back to the cell that computed it.
    link: ./guide/notebook-results
  - icon:
      src: /icons/gallery-vertical-end.svg
      alt: Document formats
      width: "24"
      height: "24"
    title: Any document
    details: Start from HTML, React, Svelte, Quarto, Typst, or LaTeX. You can bring any other framework or tool with a view provider.
    link: ./guide/formats
  - icon:
      src: /icons/mouse-pointer-click.svg
      alt: Coding agents and Lens
      width: "24"
      height: "24"
    title: Agents and Lens
    details: Ask a coding agent for a view, then point at any part of it, even a figure in a PDF, to show the agent what to change.
    link: ./guide/lens
  - icon:
      src: /icons/cpu.svg
      alt: Runtimes
      width: "24"
      height: "24"
    title: Run anywhere
    details: Serve your view with live Python, run Python in your reader's browser, or export saved results to any static host.
    link: ./guide/run-and-share
---

## Outputs as building blocks

You name the notebook results each document needs, and Studio places them: a
whole cell with its controls, one output such as a figure, or a value that
you format yourself. The same results can land in a live page and in a
typeset PDF:

<StudioFigure
  name="cell-output-value"
  alt="Three notebook cells in marimo beside an HTML page and a Typst PDF. The page shows the live slider, the level curves, and the optimal value. The PDF shows the same level curves and states the optimal value."
/>

[How Studio works](./how-studio-works) shows how a page receives your
notebook's results.

## Examples

Each example notebook backs four views, from slide decks and linked explorers
to journal papers typeset with LaTeX. Open one to compare it with its siblings
and the notebook behind them.

<StudioViewMasonry />

[Browse the examples](./examples/) or
[run one locally](./examples/#run-an-example-locally).

## Ask a coding agent

Paste this request into a terminal agent such as Claude Code or Codex:

```text
Run `uvx --with marimo-studio agent-plugins read marimo-studio` and create
a scrollytelling report and a slide deck explaining calculus basics.
```

The agent reads the instructions that ship with the `marimo-studio` package.
It starts a notebook with Studio, writes the calculus in Python cells, then
builds both views and shows them beside the notebook.
[Author with a coding agent](./guide/coding-agents) has more requests to try,
and [Getting started](./guide/getting-started) walks you through building a
view by hand.
