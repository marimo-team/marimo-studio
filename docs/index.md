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
  - icon: |
      <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <rect width="18" height="18" x="3" y="3" rx="2" />
        <path d="M3 9h18" />
        <path d="M9 21V9" />
      </svg>
    title: Building blocks
    details: Place a whole cell, one chart, or a single number wherever you need it. Each one traces back to the cell that computed it.
    link: ./guide/notebook-results
  - icon: |
      <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path d="M7 2h10" />
        <path d="M5 6h14" />
        <rect width="18" height="12" x="3" y="10" rx="2" />
      </svg>
    title: Any document
    details: Start from HTML, React, Svelte, Quarto, Typst, or LaTeX. You can bring any other framework or tool with a view provider.
    link: ./guide/formats
  - icon: |
      <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 4.1 12 6" />
        <path d="m5.1 8-2.9-.8" />
        <path d="m6 12-1.9 2" />
        <path d="M7.2 2.2 8 5.1" />
        <path d="M9.037 9.69a.498.498 0 0 1 .653-.653l11 4.5a.5.5 0 0 1-.074.949l-4.349 1.041a1 1 0 0 0-.74.739l-1.04 4.35a.5.5 0 0 1-.95.074z" />
      </svg>
    title: Agents and Lens
    details: Ask a coding agent for a view, then point at any part of it, even a figure in a PDF, to show the agent what to change.
    link: ./guide/lens
  - icon: |
      <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 20v2" />
        <path d="M12 2v2" />
        <path d="M17 20v2" />
        <path d="M17 2v2" />
        <path d="M2 12h2" />
        <path d="M2 17h2" />
        <path d="M2 7h2" />
        <path d="M20 12h2" />
        <path d="M20 17h2" />
        <path d="M20 7h2" />
        <path d="M7 20v2" />
        <path d="M7 2v2" />
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <rect x="8" y="8" width="8" height="8" rx="1" />
      </svg>
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
