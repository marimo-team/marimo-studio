---
layout: home
title: "Marimo Studio: One notebook, custom views for every audience"
titleTemplate: false
description: Keep analytical context in one reactive Marimo notebook and author custom frontends with any toolchain.

hero:
  text: Tune your notebook for every audience.
  tagline: Keep data, transformations, controls, and domain decisions in one reactive notebook. Give each audience its own focused web view.
  image:
    light: /brand/marimo-studio-lockup-stacked-light.svg
    dark: /brand/marimo-studio-lockup-stacked-dark.svg
    alt: Marimo Studio
  actions:
    - theme: brand
      text: Get started
      link: ./guide/getting-started
    - theme: alt
      text: Explore NGA
      link: ./examples/nga
    - theme: alt
      text: How Studio works
      link: ./overview

features:
  - icon:
      src: /icons/gallery-vertical-end.svg
      alt: Several custom views
      width: "24"
      height: "24"
    title: One notebook, several views
    details: Reuse one notebook graph across focused pages with their own routes, source, and interactions.
    link: ./guide/views
    linkText: Create views
  - icon:
      src: /icons/code-xml.svg
      alt: Custom frontend source
      width: "24"
      height: "24"
    title: Use any frontend stack
    details: Start with one HTML file or bring the source tree and build tools that fit the view.
    link: ./guide/authoring-options
    linkText: Author a frontend
  - icon:
      src: /icons/mouse-pointer-click.svg
      alt: Interactive notebook results
      width: "24"
      height: "24"
    title: Keep results interactive
    details: Place complete cells, rendered Python objects, values, and controls inside custom layouts.
    link: ./guide/notebook-results
    linkText: Use notebook results
  - icon:
      src: /icons/panels-top-left.svg
      alt: Live authoring workspace
      width: "24"
      height: "24"
    title: Develop beside the notebook
    details: Move among Notebook, Develop, Preview, and Source while the live kernel stays active.
    link: ./guide/live-authoring
    linkText: Use the workspace
  - icon:
      src: /icons/cpu.svg
      alt: Server and browser computation
      width: "24"
      height: "24"
    title: Run where the audience needs it
    details: Serve with Python, run a compatible notebook in the browser, or export a static site.
    link: ./guide/run-and-share
    linkText: Run and share
  - icon:
      src: /icons/bot.svg
      alt: Coding agent
      width: "24"
      height: "24"
    title: Author with an agent
    details: Inspect source, build a view, activate a browser, and validate the rendered result through one notebook-bound API.
    link: ./guide/coding-agents
    linkText: Use the agent workflow
---

## Keep analysis in the notebook

Marimo owns data access, transformations, controls, reactive execution,
sessions, and output rendering. Each Studio view owns its page structure,
styles, copy, and browser behavior.

`marimo edit` opens the notebook and view workspace. `marimo run` serves the
published views through Marimo.

## Bring the frontend that fits

A view is ordinary source plus a small `view.toml`. The default starter creates
one HTML file. Installed extensions can create any source tree and use an
existing build tool.

[Frontend authoring](guide/authoring-options.md) covers starters, source
ownership, and custom extensions.

## Place notebook results in custom layouts

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

Controls and reactive updates continue to use the notebook runtime.

[Notebook results](guide/notebook-results.md) covers targets, values, controls,
and dynamic layouts.

## Publish without losing the last good page

Studio builds from an immutable source snapshot, validates the browser files,
and atomically publishes the result. A failed build leaves the previous page
available while Source shows the new diagnostic.

[Live authoring](guide/live-authoring.md) covers source conflicts, builds, view
switching, and preview runtimes.
