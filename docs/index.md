---
layout: home
title: Marimo Studio
titleTemplate: false
description: Turn reactive Python into reports, apps, and presentations with a coding agent.

hero:
  text: Web views for reactive Python notebooks
  tagline: Turn reactive Python into reports, apps, and presentations. Work with a coding agent, and keep every view connected to your analysis.
  image:
    light: /brand/marimo-studio-lockup-stacked-light.svg
    dark: /brand/marimo-studio-lockup-stacked-dark.svg
    alt: Marimo Studio
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

## Ask a coding agent for a view

Ask your coding agent to turn an existing notebook into a view for your audience:

> Create a concise briefing from this notebook. Keep the results connected to
> Python, add a way to explore them, and check the view on a narrow screen.

Studio ships the instructions and API your agent needs with the Python package.
Read its installed briefing from a terminal:

```console
uvx --with marimo-studio agent-plugins read marimo-studio
```

[Connect your agent](./guide/coding-agents) or
[create your first view](./guide/getting-started).
