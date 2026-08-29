---
title: Choose a frontend starter
description: Choose page source that matches the interaction and maintenance needs of the audience experience.
---

# Choose a frontend starter

Choose the lightest frontend that makes the page comfortable to build and
maintain. Every choice can place the same notebook results and remains editable
in Studio.

## Keep a focused page in one HTML file

Choose HTML when the work is mainly layout, wording, styles, and a small amount
of browser interaction. The base installation creates one `index.html` with
inline CSS and JavaScript:

```console
marimo-studio view create dashboard --target analysis.py
```

This keeps reports, dashboards, and small tools close to the content they
present. No separate frontend build environment is required.

## Use React for a component application

Choose React when the page has reusable components, complex local interaction,
or an existing React codebase that the team already maintains.

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create dashboard \
  --target analysis.py \
  --starter marimo-studio/react:default
```

Studio creates TSX, CSS, and Deno configuration. The optional Deno dependency
builds the frontend without adding Node package management to the notebook
environment.

## Present a Reveal.js slide deck

Choose Reveal.js when the audience should move through an ordered presentation
with slide navigation, fragments, and notebook results placed beside the claim
they support.

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create slides \
  --target analysis.py \
  --starter marimo-studio/react:reveal
```

Studio creates a React deck with `@revealjs/react`, Reveal's structural CSS, a
local visual theme, and frozen Deno dependencies. Add selected notebook cells,
outputs, or values inside `Slide` components.

## Use Svelte for concise components

Choose Svelte when the page benefits from components and reactive browser state
with less component boilerplate.

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create story \
  --target analysis.py \
  --starter marimo-studio/svelte:default
```

Studio creates Svelte, TypeScript, CSS, Vite, and Deno configuration. The page
still reads notebook results through the same HTML elements and attributes used
by the one-file page.

## Inspect the available starting points

```console
marimo-studio starters
```

The command shows the installed choices, the files each one creates, and any
setup needed before it can build. Its stable identifier is accepted by
`view create --starter`.

## Connect another frontend build

An existing frontend project can remain the source of the page. A small Python
integration tells Studio which files people can edit and how to build the
browser output. Studio calls this integration a **view provider**.

Read [Add support for another frontend](../reference/provider-api.md) when a
team needs that extension point.
