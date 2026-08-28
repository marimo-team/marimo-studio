---
layout: home
title: Marimo Studio
titleTemplate: false
description: Turn one reactive Marimo notebook into focused web pages for different audiences.

hero:
  text: Build focused pages from one notebook.
  tagline: Keep data and computation in marimo. Shape the page each audience needs.
  image:
    light: /brand/marimo-studio-lockup-stacked-light.svg
    dark: /brand/marimo-studio-lockup-stacked-dark.svg
    alt: Marimo Studio
  actions:
    - theme: brand
      text: Create your first page
      link: ./guide/getting-started
    - theme: alt
      text: See the NGA example
      link: ./examples/nga
    - theme: alt
      text: Author with an agent
      link: ./guide/coding-agents

features:
  - icon:
      src: /icons/gallery-vertical-end.svg
      alt: Several audience pages
      width: "24"
      height: "24"
    title: One notebook, several audiences
    details: Reuse the same data, controls, and results across pages that explain and present them differently.
    link: ./guide/views
    linkText: Create audience pages
  - icon:
      src: /icons/panels-top-left.svg
      alt: Notebook, source, and preview
      width: "24"
      height: "24"
    title: Edit beside the notebook
    details: Work with Python, page source, and the rendered result while the notebook session stays active.
    link: ./guide/work-in-studio
    linkText: Work in Studio
  - icon:
      src: /icons/bot.svg
      alt: Coding agent
      width: "24"
      height: "24"
    title: Let an agent verify the page
    details: Agents inspect the same notebook and source, save safely, show the result, and validate the rendered page.
    link: ./guide/coding-agents
    linkText: Use the agent workflow
---

## Create one page

Start with a saved notebook such as `analysis.py`:

```console
uvx marimo-studio view create dashboard --target analysis.py
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

The first command creates editable page source beside the notebook. The second
opens Notebook, Source, and Preview together. Saving Source rebuilds Preview,
while a failed build leaves the last successful page available.

![Notebook, page source, and Preview together in Develop](/screenshots/studio-develop.png)

Studio calls each named page a **view**. Create another view when a different
audience needs different wording, layout, or interaction from the same
notebook.

## Keep the analytical model in marimo

The notebook owns data access, transformations, controls, and reusable results.
The page owns its structure, copy, styles, and browser behavior.

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

[Place notebook results on a page](guide/notebook-results.md) explains these
three forms through complete examples.

## Choose where the notebook runs

Use Python execution when the notebook needs local files, databases, server
credentials, or packages unavailable in the browser. Use browser execution or
static export when the notebook and its data can run in Pyodide.

[Run or publish a page](guide/run-and-share.md) keeps the code and data exposure
rules beside each deployment command.
