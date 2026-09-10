---
layout: home
title: Marimo Studio
titleTemplate: false
description: Build named web views from one reactive marimo notebook.

hero:
  text: Custom web views from one notebook.
  tagline: Build reports, apps, and slides around a reactive Python notebook.
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
    details: Give each app, report, or deck its own frontend and route.
    link: ./guide/views
  - icon:
      src: /icons/code-xml.svg
      alt: Frontend source
      width: "24"
      height: "24"
    title: Web frontends
    details: Use HTML, React, Svelte, or Reveal.js.
    link: ./guide/frontend-options
  - icon:
      src: /icons/cpu.svg
      alt: Notebook runtime
      width: "24"
      height: "24"
    title: Run and share
    details: Run with Python, in WebAssembly, or as a Prepared static export.
    link: ./guide/run-and-share
---

## One notebook, many views

<StudioExample family="athletes" />
