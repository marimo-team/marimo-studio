---
layout: home
title: "Marimo Studio: One notebook, custom views for every audience"
titleTemplate: false
description: Keep analytical context in one reactive, reproducible Marimo notebook. Shape custom web views for each audience with HTML, CSS, and JavaScript.

hero:
  text: Tune your notebook for every audience.
  tagline: Keep data access, transformations, metrics, controls, and domain decisions in one reactive notebook. Create custom web views in standard web files that coding agents can inspect and edit.
  image:
    light: /brand/marimo-studio-lockup-stacked-light.svg
    dark: /brand/marimo-studio-lockup-stacked-dark.svg
    alt: Marimo Studio
  actions:
    - theme: brand
      text: Get started
      link: ./guide/getting-started
    - theme: alt
      text: See the examples
      link: ./examples/
    - theme: alt
      text: How Studio works
      link: ./overview

features:
  - icon:
      src: /icons/blocks.svg
      alt: Durable analytical context
      width: "24"
      height: "24"
    title: Keep notebook cells focused
    details: Use notebook cells for data access, transformations, metrics, controls, and domain decisions. Keep structure, styling, and browser behavior in ordinary web files.
    link: ./overview#keep-analysis-in-notebook-cells-and-frontend-code-in-view-files
    linkText: Understand the model
  - icon:
      src: /icons/panels-top-left.svg
      alt: Several authored views
      width: "24"
      height: "24"
    title: One notebook, several views
    details: Reuse one reactive graph across pages that each have their own audience, structure, language, styling, and route.
    link: ./guide/views
    linkText: Create and manage views
  - icon:
      src: /icons/code-xml.svg
      alt: HTML, CSS, and JavaScript
      width: "24"
      height: "24"
    title: Use the web platform
    details: Author complete HTML documents with CSS, JavaScript modules, browser APIs, components, libraries, and native Marimo outputs.
    link: ./guide/web-platform
    linkText: Use browser APIs
  - icon:
      src: /icons/sparkles.svg
      alt: Coding agents
      width: "24"
      height: "24"
    title: Agent-native authoring
    details: Coding agents inspect and edit ordinary web files while metric definitions, transformations, and domain rules remain visible in the notebook.
    link: ./guide/coding-agents
    linkText: Use the authoring workflow
---

## Keep analysis in notebook cells and frontend code in view files

Marimo provides a reactive notebook editor for data access, transformations,
metrics, controls, and domain decisions. Studio views put page structure, CSS,
JavaScript, assets, and browser behavior in ordinary web files.

Coding agents can reshape the interface through these web files while notebook
cells remain focused on the analytical model. Each view projects live notebook
results, so the executable, reviewable context continues to evolve in one
place.

::: info Studio runs inside Marimo
`marimo edit` opens the notebook and view together. `marimo run` serves the
finished views with Marimo's kernels, sessions, authentication, routing,
controls, and output renderers.
:::

## One notebook, several outcomes

An analyst workbench, an operations dashboard, and an executive brief can use
the same reactive notebook. Each view chooses the results, reading order,
language, interaction, and delivery mode its audience needs.

Studio connects the notebook to each view through three primitives:

| Need                                               | Projection                    |
| -------------------------------------------------- | ----------------------------- |
| Include everything a cell produced                 | `<marimo-cell name="...">`    |
| Render one Python object through Marimo            | `<marimo-output value="...">` |
| Read a JSON-compatible value in HTML or JavaScript | `mo-value="..."`              |

[Create your first view](guide/getting-started.md) or
[compare the included examples](examples/).
