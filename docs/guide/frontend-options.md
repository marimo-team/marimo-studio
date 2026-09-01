---
title: Choose a frontend
description: Match each view to the smallest frontend and browser library that supports its task.
---

# Choose a frontend

Start with browser-native HTML. Keep a small view in one file, or move its CSS
and JavaScript into direct local references. Move to React or Svelte when
component structure, imported assets, or a larger module graph makes that source
easier to maintain.

Every frontend uses the same `marimo-cell`, `marimo-output`, and `mo-value`
projection contract.

## Vanilla HTML

Choose the default starter for reports, small tools, and browser-native views:

```console
marimo-studio view create report --target analysis.py
```

The generated `index.html` contains inline CSS and JavaScript. Keep that shape
for a small view, or split direct local sources:

```html
<link rel="stylesheet" href="./style.css" />
<script type="module" src="./main.js"></script>
```

Studio resolves each local path relative to the entry HTML. Safe parent paths
inside the view project, nested entrypoints, query strings, and fragments remain
valid. Keep that base explicit by leaving `<base href>` out of the entry
document. Each resolved `.css`, `.js`, or `.mjs` file appears in Source,
invalidates the build when it changes, and publishes at the same artifact path.
An HTTP or HTTPS dependency URL must include `//` and a host.

The Vanilla provider publishes the files named by those direct tags. Bundle
JavaScript imports into the referenced script. Encode CSS assets as data URLs or
load them from an external URL you trust. Choose another frontend provider when
the build should traverse a complete source tree. Inspection reports a
source-located error for local CSS `url()` or `@import` dependencies, local
JavaScript imports or re-exports, and computed dynamic imports. Import maps and
source-phase imports require a provider that builds the JavaScript module graph.
Inspection fails closed when the pinned JavaScript grammar cannot establish the
dependency boundary. The athlete report uses browser APIs. The three-file
athlete field briefing adds Shower and Three.js. The earthquake story imports
Observable Plot.

Tree-sitter JavaScript 0.25 rejects a regex statement immediately after a
`break` or `continue` terminated through automatic semicolon insertion, even
though browsers parse that unreachable statement. Terminate `break` and
`continue` explicitly with `;` when another statement follows on the next line.
The same grammar rejects import attributes on re-export statements. Import the
remote module with its attributes, then export the local binding:

```js
import data from "https://cdn.example.test/data.json" with { type: "json" };
export { data as default };
```

Enumerate named exports the same way. Choose a provider that builds the module
graph when the view needs a wildcard re-export with import attributes.

## React

Choose React for component applications and existing React teams:

```console
uvx --from 'marimo-studio[deno]==0.1.0' marimo-studio view create operations \
  --target analysis.py \
  --starter marimo-studio/react:default
```

Studio creates TSX, CSS, Deno configuration, and a frozen dependency lock. Add
exact npm imports to `deno.json`. The earthquake operations view uses MapLibre,
and the occupancy model review uses Recharts.

## React with Reveal.js

Choose the Reveal starter for ordered presentations:

```console
uvx --from 'marimo-studio[deno]==0.1.0' marimo-studio view create briefing \
  --target analysis.py \
  --starter marimo-studio/react:reveal
```

The starter supplies Reveal.js structure, navigation, fragments, overview, and
speaker-ready slide semantics. Notebook controls and dependent results can live
inside a slide, as the earthquake briefing demonstrates.

## Svelte

Choose Svelte for component views built around concise reactive browser state:

```console
uvx --from 'marimo-studio[deno]==0.1.0' marimo-studio view create explorer \
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
