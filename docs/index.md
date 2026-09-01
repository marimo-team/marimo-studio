---
layout: home
title: Marimo Studio
titleTemplate: false
description: Build multiple custom web views from one marimo notebook with modern web tools and coding agents.

hero:
  text: Custom web views from one notebook.
  tagline: Build with modern web tools and coding agents while marimo keeps Python computation reactive.
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
    - theme: alt
      text: How it works
      link: ./what-is-studio

features:
  - icon:
      src: /icons/panels-top-left.svg
      alt: Reactive notebook
      width: "24"
      height: "24"
    title: One notebook
    details: Keep Python computation, controls, and reusable results together in one reactive marimo notebook.
    link: ./what-is-studio
    linkText: How Studio works
  - icon:
      src: /icons/gallery-vertical-end.svg
      alt: Custom web views
      width: "24"
      height: "24"
    title: Custom web views
    details: Build reports, apps, and presentations with HTML, CSS, JavaScript, React, or Svelte.
    link: ./guide/frontend-options
    linkText: Choose a frontend
  - icon:
      src: /icons/bot.svg
      alt: Coding agent
      width: "24"
      height: "24"
    title: Agent-native authoring
    details: Coding agents inspect the notebook, edit view source, build previews, and validate the result.
    link: ./guide/coding-agents
    linkText: Author with an agent
---

Marimo Studio 0.1 is experimental. Public contracts may change between minor
releases before 1.0. See [Compatibility and support](reference/compatibility.md).

## See it in action

<StudioExample family="athletes" />

[Explore all examples](examples/index.md) or [create your first
view](guide/getting-started.md).
