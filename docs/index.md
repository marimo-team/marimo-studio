---
layout: home
title: marimo-studio
titleTemplate: false
description: Turn reactive Python into reports, apps, and presentations with a coding agent.

hero:
  text: Web views for reactive Python notebooks
  tagline: Turn reactive Python into reports, apps, and presentations. Work with a coding agent, and keep every view connected to your analysis.
  image:
    light: /brand/marimo-studio-lockup-stacked-light.svg
    dark: /brand/marimo-studio-lockup-stacked-dark.svg
    alt: marimo-studio
  actions:
    - theme: brand
      text: Get started
      link: ./guide/getting-started
    - theme: alt
      text: Examples
      link: ./examples/

features:
  - icon:
      src: /icons/panels-top-left.svg
      alt: Reactive notebook
      width: "24"
      height: "24"
    title: Reactive Python
    details: Keep data, computation, and controls in one notebook.
    link: ./what-is-studio
  - icon:
      src: /icons/gallery-vertical-end.svg
      alt: Named web views
      width: "24"
      height: "24"
    title: Named views
    details: Give a report, an explorer, or a lesson its own layout and interactions.
    link: ./guide/views
  - icon:
      src: /icons/code-xml.svg
      alt: Coding agent
      width: "24"
      height: "24"
    title: Author with a coding agent
    details: Ask for a view. Your agent can inspect the notebook, edit the source, and verify the result.
    link: ./guide/coding-agents
  - icon:
      src: /icons/cpu.svg
      alt: Notebook runtime
      width: "24"
      height: "24"
    title: Run or export
    details: Serve a live Python app, run Python in the browser, or publish precomputed results.
    link: ./guide/run-and-share
---

## Example: Quadratic programs

Teach the same optimization problem as a lecture, a reading page, or a hands-on
lab. Each view reads from the same Python notebook.

<StudioViewStack family="quadratic-programs" />

## Example views

Each example notebook backs several views: slide decks, reading pages, linked
explorers, maps, monitors, and printable reports. Open a view to compare it
with its siblings and the notebook behind them.

<StudioViewMasonry />

[Browse the examples](./examples/) or
[run one locally](./examples/#run-an-example-locally).

## Ask a coding agent for a view

Give a terminal agent one instruction:

```console
claude 'Follow `uvx --with marimo-studio agent-plugins read marimo-studio`
to build a briefing view of analysis.py that leads with the headline results.'
```

The briefing ships with the `marimo-studio` package. It tells the agent how to
pair with your running notebook, or start one, then create, build, and show the
view beside the notebook.

[Author with a coding agent](./guide/coding-agents) or
[create your first view](./guide/getting-started).
