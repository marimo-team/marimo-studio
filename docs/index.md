---
layout: home
title: Marimo Studio
titleTemplate: false
description: Keep one reproducible notebook as the analytical model and build a purpose-built web view for each job.

hero:
  text: One notebook. A studio for every view.
  tagline: Marimo Studio keeps Python computation in a reactive notebook while each view uses modern frontend tools for a different job.
  image:
    light: /brand/marimo-studio-lockup-stacked-light.svg
    dark: /brand/marimo-studio-lockup-stacked-dark.svg
    alt: Marimo Studio
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
      alt: Reactive notebook
      width: "24"
      height: "24"
    title: Reproducible analysis
    details: The notebook keeps data access, transformations, controls, and reusable results together as one reactive Python program.
    link: ./why-studio
    linkText: Why Studio?
  - icon:
      src: /icons/gallery-vertical-end.svg
      alt: Custom web views
      width: "24"
      height: "24"
    title: Purpose-built views
    details: Each named view owns its frontend source, layout, and interaction while drawing from notebook cells, outputs, and values.
    link: ./guide/frontend-options
    linkText: Choose a frontend
  - icon:
      src: /icons/bot.svg
      alt: Coding agent
      width: "24"
      height: "24"
    title: Agent-native authoring
    details: People and agents inspect the same notebook and view source, make revision-safe edits, build, preview, and validate the rendered result.
    link: ./guide/coding-agents
    linkText: Author with an agent
  - icon:
      src: /icons/cpu.svg
      alt: Python and WebAssembly runtimes
      width: "24"
      height: "24"
    title: Pluggable Runtimes
    details: Keep view source fixed while the notebook runs on a Python server, in a browser worker, or as a static export.
    link: ./guide/run-and-share
    linkText: Run or publish
---

## The same analysis, three distinct views

A publication report, a linked explorer, and a Three.js briefing all draw from
the Rio athlete notebook.

<StudioExample family="athletes" />

Each view is an independent frontend project connected to the notebook's data,
computation, controls, and results.

[Explore all examples](examples/index.md) or [create your first
view](guide/getting-started.md).
