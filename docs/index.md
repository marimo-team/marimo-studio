---
layout: home
title: Marimo Studio
titleTemplate: false
description: Build named web views from one reactive marimo notebook.

hero:
  text: Custom web views from one notebook.
  tagline: Keep Python computation reactive in marimo while each named view uses the frontend, layout, and interaction its audience needs.
  image:
    light: /brand/marimo-studio-lockup-stacked-light.svg
    dark: /brand/marimo-studio-lockup-stacked-dark.svg
    alt: Marimo Studio
  actions:
    - theme: brand
      text: Create your first view
      link: ./guide/getting-started
    - theme: alt
      text: Follow the learning path
      link: ./guide/
    - theme: alt
      text: Explore examples
      link: ./examples/

features:
  - icon:
      src: /icons/panels-top-left.svg
      alt: Reactive notebook
      width: "24"
      height: "24"
    title: Preserve the analysis
    details: Keep data access, Python computation, controls, and reusable results in one saved reactive notebook.
    link: ./what-is-studio
    linkText: Understand the model
  - icon:
      src: /icons/gallery-vertical-end.svg
      alt: Named web views
      width: "24"
      height: "24"
    title: Build named views
    details: Give each report, app, explorer, monitor, or deck its own frontend project and route.
    link: ./guide/views
    linkText: Work with views
  - icon:
      src: /icons/code-xml.svg
      alt: Frontend source
      width: "24"
      height: "24"
    title: Use normal web tools
    details: Start with HTML or use React, Svelte, Reveal.js, and browser libraries through view providers.
    link: ./guide/frontend-options
    linkText: Choose a frontend
  - icon:
      src: /icons/cpu.svg
      alt: Notebook runtime
      width: "24"
      height: "24"
    title: Choose where Python runs
    details: Use the Python runtime for server resources or the Browser runtime for WebAssembly and static export.
    link: ./guide/run-and-share
    linkText: Compare runtimes
---

## One notebook, many views

<StudioExample family="athletes" />

[Explore all examples](examples/index.md), [open the reference](reference/index.md),
or [troubleshoot a problem](guide/troubleshooting.md).

## Start with one result

1. [Create a view](guide/getting-started.md) from a saved notebook.
2. [Place a notebook result](guide/notebook-results.md) in its frontend source.
3. [Edit and preview](guide/work-in-studio.md) the notebook and view together.
4. [Run or export](guide/run-and-share.md) the finished presentation.

Continue through [source management](guide/manage-source.md),
[styling](guide/styling.md), [navigation](guide/navigation-and-sessions.md),
[deployment](guide/deploy.md), agents, and recovery. Use
[Reference](reference/index.md) for exact commands, APIs, configuration, events,
identities, errors, and limits.
