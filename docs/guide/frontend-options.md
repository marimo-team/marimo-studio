---
title: Choose a frontend
description: Match each view to the smallest frontend and browser toolchain that supports its task.
---

# Choose a frontend

Start with Vanilla HTML, CSS, and JavaScript. Choose
[React](https://react.dev/) or [Svelte](https://svelte.dev/) when component
structure, imported assets, or a larger module graph makes the view project
easier to maintain. Choose [Observable Notebook Kit](https://observablehq.com/notebook-kit/kit)
for reactive JavaScript, Markdown, and HTML cells.

Every built-in view provider supports `marimo-cell`, `marimo-output`, and
`mo-value`. Add support for any web framework or custom build workflow with a
[view provider](../reference/provider-api.md).

| Starter                              | Choose it for                                             |
| ------------------------------------ | --------------------------------------------------------- |
| `marimo-studio/vanilla:default`      | Reports, small tools, and browser-native pages            |
| `marimo-studio/react:default`        | Typed React applications and component systems            |
| `marimo-studio/react:reveal`         | Ordered [Reveal.js](https://revealjs.com/) presentations  |
| `marimo-studio/svelte:default`       | Svelte applications with concise reactive browser state   |
| `marimo-studio/notebook-kit:default` | Observable notebook HTML with reactive presentation cells |

## Vanilla HTML

Create the default starter:

```console
marimo-studio view create report --target analysis.py
```

The starter creates `index.html` and `AGENTS.md`. It populates the document
with the notebook cells that may display output and supplies an inline
`observeMarimoValue` adapter.

Keep CSS and JavaScript inline for a compact page, or reference local leaf
files directly:

```html
<link rel="stylesheet" href="./style.css" />
<script type="module" src="./main.js"></script>
```

The Vanilla provider publishes those directly referenced `.css`, `.js`, and
`.mjs` files at the same artifact paths. Local CSS imports, CSS asset URLs, and
JavaScript module imports require bundling or another provider. Remote modules
require browser network access and a hosting
[Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)
that allows their origins.

Leave `<base href>` out of the authored entry document. Studio supplies the
delivery base when it publishes the artifact.

Run Deno commands through the notebook's Python environment with
`marimo-studio[deno]` installed so dependency changes and Studio builds use the
same Deno version.

## React

Create a typed React project with the pinned [Deno](https://docs.deno.com/)
JavaScript and TypeScript toolchain:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create operations \
  --target analysis.py \
  --starter marimo-studio/react:default
```

The starter includes [TypeScript](https://www.typescriptlang.org/) with JSX
markup in `.tsx` files, CSS, custom-element declarations, a
`useMarimoValue` hook, `deno.json`, and a frozen lockfile. Its build runs type
checking before bundling.

Add an exact dependency from the view project root:

```console
uv run -- deno add --frozen=false --save-exact npm:d3@7
```

Commit `deno.json` and `deno.lock` after an intentional update. Normal Studio
builds keep the lockfile frozen.

## React with Reveal.js

Create a slide deck:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create briefing \
  --target analysis.py \
  --starter marimo-studio/react:reveal
```

The starter supplies Reveal.js structure, navigation, fragments, overview, and
one initial slide for each notebook cell that may display output. Place Marimo
controls and dependent results directly inside a slide.

## Svelte

Create a typed Svelte project:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create explorer \
  --target analysis.py \
  --starter marimo-studio/svelte:default
```

The starter includes Svelte, TypeScript,
[Vite](https://vite.dev/), a frontend development and build tool, an
`observeMarimoValue` action, `package.json`, Deno configuration, and a frozen
lockfile. Its build runs `svelte-check` before Vite.

Add an exact application dependency from the view project root:

```console
uv run -- deno add --package-json --frozen=false --save-exact npm:d3@7
```

Commit `package.json` and `deno.lock` after the update.

## Observable Notebook Kit

[Observable Notebook Kit](https://observablehq.com/notebook-kit/kit) demonstrates
a bespoke provider integration: its notebook HTML format and reactive JavaScript
runtime work with the same Marimo projections as the other frontends.

Create an Observable notebook view:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create report \
  --target analysis.py \
  --starter marimo-studio/notebook-kit:default
```

Write Notebook Kit cells in `src/index.html`. Put `marimo-cell`, `marimo-output`,
and `mo-value` hosts inside `type="text/html"` cells. The supplied
`marimoValue(host)` generator connects a declared value host to Observable's
reactive graph. Keep shared computations and controls in the Marimo notebook.

The starter builds through Vite and Deno with frozen dependencies. Edit the
page template in `src/page.tmpl` and styles in `src/style.css`. See the
[Notebook Kit provider reference](../reference/built-in-providers.md#marimo-studio-notebook-kit)
for value subscriptions, interpolated targets, and project options.

## Inspect installed starters

```console
marimo-studio starters
```

Human-readable output lists the starter ID, summary, provider, availability,
and setup action. Use JSON when a tool needs the advertised source-document
plan:

```console
marimo-studio starters --json
```

The **Files created** detail in Studio shows the same document plan before view
creation. A starter may also create provider-owned files required by its build.

Use [Manage view source](manage-source.md) for the distinction between source
documents and build inputs. Teams can add another project shape through a
[view provider](../reference/provider-api.md).
