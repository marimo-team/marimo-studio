---
layout: home
title: marimo-studio
titleTemplate: false
description: Build web pages, slide decks, and Typst or LaTeX documents from the cells, outputs, and values of a marimo notebook.

hero:
  text: Custom views of marimo notebooks
  tagline: Place a notebook's cells, outputs, and values in web pages, slide decks, and Typst or LaTeX documents. The notebook keeps the analysis, and each view keeps its own source.
  image:
    light: /brand/marimo-studio-lockup-stacked-light.svg
    dark: /brand/marimo-studio-lockup-stacked-dark.svg
    alt: marimo-studio
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
    title: Results by name
    details: A view places a cell, an output, or a value. Studio resolves each name to the cell that computes it.
    link: ./guide/notebook-results
  - icon:
      src: /icons/gallery-vertical-end.svg
      alt: View formats
      width: "24"
      height: "24"
    title: Pages and documents
    details: Write a view in HTML, React, Svelte, Reveal.js, Quarto, Typst, or LaTeX, or add a provider for another tool.
    link: ./guide/formats
  - icon:
      src: /icons/code-xml.svg
      alt: Coding agent
      width: "24"
      height: "24"
    title: Coding agents
    details: Studio ships instructions for agents. An agent writes view source beside the notebook and checks the result in Preview.
    link: ./guide/coding-agents
  - icon:
      src: /icons/cpu.svg
      alt: Notebook runtime
      width: "24"
      height: "24"
    title: Run or export
    details: Serve a live Python app, run Python in the browser, or export prepared results as static files.
    link: ./guide/run-and-share
---

## Examples

Each example notebook backs four views, from slide decks and linked explorers
to journal papers typeset with LaTeX. Open a view to compare it with its
siblings and the notebook behind them.

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
and [Getting started](./guide/getting-started) builds a view by hand.
