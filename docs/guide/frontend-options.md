---
title: Choose a frontend
description: Match each view to the smallest frontend and browser library that supports its task.
---

# Choose a frontend

Start with one HTML file. Move to React or Svelte when component structure and
browser interaction make that source easier to maintain.

Every frontend uses the same `marimo-cell`, `marimo-output`, and `mo-value`
projection contract.

## Vanilla HTML

Choose the default starter for reports, small tools, and pages whose source fits
comfortably in one document:

```console
marimo-studio view create report --target analysis.py
```

The generated `index.html` contains inline CSS and JavaScript. Import a browser
library from a trusted ECMAScript module URL when one focused dependency serves
the view. The athlete report uses browser APIs, the athlete field briefing adds
Shower and Three.js, and the earthquake story imports Observable Plot.

## React

Choose React for component applications and existing React teams:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create operations \
  --target analysis.py \
  --starter marimo-studio/react:default
```

Studio creates TSX, CSS, Deno configuration, and a frozen dependency lock. Add
exact npm imports to `deno.json`. The earthquake operations view uses MapLibre,
and the occupancy model review uses Recharts.

## React with Reveal.js

Choose the Reveal starter for ordered presentations:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create briefing \
  --target analysis.py \
  --starter marimo-studio/react:reveal
```

The starter supplies Reveal.js structure, navigation, fragments, overview, and
speaker-ready slide semantics. Notebook controls and dependent results can live
inside a slide, as the earthquake briefing demonstrates.

## Svelte

Choose Svelte for component views built around concise reactive browser state:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create explorer \
  --target analysis.py \
  --starter marimo-studio/svelte:default
```

Studio creates Svelte, TypeScript, CSS, Vite, Deno configuration, and a frozen
dependency lock. The athlete explorer adds Mosaic, vgplot, and DuckDB-WASM. The
occupancy monitor adds ECharts.

## Inspect installed starters

```console
marimo-studio starters
```

The command lists each stable starter ID, generated files, provider, and setup
action.

A team can preserve another frontend project by implementing a
[view provider](../reference/provider-api.md). The provider declares editable
source, build inputs, and the command that produces the browser artifact.
