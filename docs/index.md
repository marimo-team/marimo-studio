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
      src: /icons/gallery-vertical-end.svg
      alt: Several authored views
      width: "24"
      height: "24"
    title: One notebook, several views
    details: Reuse one reactive graph across pages that each have their own audience, structure, language, styling, and route.
    link: ./guide/views
    linkText: Create and manage views
  - icon:
      src: /icons/mouse-pointer-click.svg
      alt: Interactive notebook results
      width: "24"
      height: "24"
    title: Keep results interactive
    details: Place complete cells, individual Python objects, or JSON-compatible values. Marimo tables, plots, controls, downloads, and anywidgets retain their native behavior.
    link: ./guide/notebook-results
    linkText: Choose a projection
  - icon:
      src: /icons/panels-top-left.svg
      alt: Live authoring workspace
      width: "24"
      height: "24"
    title: Build beside the notebook
    details: Move among the notebook, source, and preview while preserving the live kernel and each preview runtime. Edit in Studio or your regular editor.
    link: ./guide/live-authoring
    linkText: Use the live workspace
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
      src: /icons/cpu.svg
      alt: Server and browser computation
      width: "24"
      height: "24"
    title: Choose where computation runs
    details: Serve a Python-backed application, run the notebook in a browser worker, or export a self-contained static site from the same authored view.
    link: ./guide/run-and-share
    linkText: Compare delivery options
  - icon:
      src: /icons/bot.svg
      alt: Coding agent
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

## Author against the live result

Use **Notebook** for analytical work, **Build** to compare the notebook and
page, **Preview** for audience review, and **HTML & CSS** for source feedback.
Studio keeps the underlying notebook and prepared preview runtimes available
while the workspace arrangement changes.

Browser saves and external editor saves converge on the same view files. If
both changed from the same earlier revision, Studio preserves each version so
you can compare them and choose the intended source. CSS and script-free HTML
refresh around mounted Marimo results, which keeps interactive state in place
during frequent layout work.

[Author with the live workspace](guide/live-authoring.md) covers layouts,
source conflicts, refresh behavior, runtime comparison, and query-driven
views.

## Deliver for the environment your audience has

Use the Server runtime when the view needs Python packages, local files,
databases, credentials, or server-side network access. Use WebAssembly when
the notebook and its dependencies can run in Pyodide. Export the WebAssembly
form when the audience needs a static site.

The authored view stays the same across these delivery choices. You can test
Server and WebAssembly previews during authoring, then serve through
`marimo run`, mount Studio in an ASGI application, or publish a static export.

[Run, export, and share](guide/run-and-share.md) develops each path and its
data boundary.
