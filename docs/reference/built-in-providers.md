---
title: Built-in view providers
description: Provider keys, starter IDs, source documents, requirements, and view.toml options included with Marimo Studio.
---

# Built-in view providers

Marimo Studio includes Vanilla HTML, [React](https://react.dev/),
[Svelte](https://svelte.dev/), and
[Observable Notebook Kit](https://observablehq.com/notebook-kit/kit) view providers. A provider key selects the view
project's inspection and build contract. A starter ID selects the files created
for a new view project.

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

Studio Source writes preserve the provider key. Create another view with the
desired starter when changing frontend stacks. Starter identity is creation
input and is not stored in `view.toml`.

## Catalog

| Provider key                 | Starter IDs                                                 | Build requirement        |
| ---------------------------- | ----------------------------------------------------------- | ------------------------ |
| `marimo-studio/vanilla`      | `marimo-studio/vanilla:default`                             | Base Studio installation |
| `marimo-studio/react`        | `marimo-studio/react:default`, `marimo-studio/react:reveal` | `marimo-studio[deno]`    |
| `marimo-studio/svelte`       | `marimo-studio/svelte:default`                              | `marimo-studio[deno]`    |
| `marimo-studio/notebook-kit` | `marimo-studio/notebook-kit:default`                        | `marimo-studio[deno]`    |

Run `marimo-studio starters --json` for the installed catalog and current
availability. The `documents` field is the starter's initial Source document
plan. `view create --dry-run` reports every file Studio will create or update.

## `marimo-studio/vanilla`

The Vanilla provider publishes browser-native HTML with directly referenced
local CSS and JavaScript.

The default starter creates these provider-owned files:

```text
AGENTS.md
index.html
```

Studio adds `view.toml` to the view project and Source catalog.

The starter loads pinned UnoCSS runtime and Iconify Icon web component scripts
from jsDelivr. UnoCSS utility classes are available in authored HTML, and
`iconify-icon` elements render named icons. Serving the page requires network
access to jsDelivr, and Iconify API icons require access to their configured API
origin. The hosting content security policy must admit those origins.

`index.html` contains one `<marimo-cell>` for each enabled notebook cell that
static inspection determines may display output. `AGENTS.md` describes the
view-authoring contract for a coding agent working in Source.

Project-relative POSIX paths use forward slashes and start at the view project
root, even when Studio runs on Windows.

The provider adds a directly referenced local stylesheet or script to Source
and the build input set. Keep other local assets inline in the entry document.
See [Notebook result projections](projections.md) for projection elements and
selectors.

### Options

| Option       | Type                        | Default      | Contract                        |
| ------------ | --------------------------- | ------------ | ------------------------------- |
| `entrypoint` | Project-relative POSIX path | `index.html` | Selects the HTML entry document |

Unknown options and paths outside the view project produce a
`provider-options-invalid` diagnostic.

## `marimo-studio/react`

The React provider inspects [TypeScript](https://www.typescriptlang.org/) and
JavaScript source, reports JSX markup that requests notebook results, and
builds an HTML artifact with the pinned
[Deno](https://docs.deno.com/) JavaScript and TypeScript toolchain. `deno.lock`
appears in Source as read-only.

### React starter

`marimo-studio/react:default` creates this initial Source document plan:

```text
AGENTS.md
deno.json
deno.lock
src/App.tsx
src/index.html
src/lib/use-marimo-value.ts
src/main.tsx
src/marimo-studio.d.ts
src/style.css
```

`src/App.tsx` contains one `<marimo-cell>` for each enabled notebook cell that
may display output. `useMarimoValue()` subscribes a React component to a
declared `mo-value` host.

### Reveal.js starter

`marimo-studio/react:reveal` creates a [Reveal.js](https://revealjs.com/) slide
deck. It uses the same project shape as the React starter and places one
eligible notebook cell on each slide.

The provider builds `src/index.html` as the HTML entry document.

### Options

| Option     | Type                        | Default        | Contract                                                |
| ---------- | --------------------------- | -------------- | ------------------------------------------------------- |
| `main`     | Project-relative POSIX path | `src/main.tsx` | Selects the React module imported by the entry document |
| `config`   | Project-relative POSIX path | `deno.json`    | Selects the Deno configuration                          |
| `lockfile` | Project-relative POSIX path | `deno.lock`    | Selects the frozen Deno lockfile                        |

## `marimo-studio/svelte`

The Svelte provider inspects Svelte, TypeScript, and JavaScript source, reports
template sites that request notebook results, and builds an HTML artifact with
[Vite](https://vite.dev/), a frontend build tool, through the pinned Deno
toolchain. `deno.lock` and `src/vite-env.d.ts` appear in Source as read-only.

The default starter creates this initial Source document plan:

```text
AGENTS.md
deno.json
deno.lock
package.json
src/App.svelte
src/app.d.ts
src/index.html
src/lib/marimo-value.ts
src/main.ts
src/style.css
src/vite-env.d.ts
svelte.config.js
tsconfig.json
vite.config.ts
```

`src/App.svelte` contains one `<marimo-cell>` for each enabled notebook cell
that may display output. `observeMarimoValue()` subscribes a Svelte action to a
declared `mo-value` host.

### Options

| Option        | Type                        | Default          | Contract                                                               |
| ------------- | --------------------------- | ---------------- | ---------------------------------------------------------------------- |
| `entrypoint`  | Project-relative POSIX path | `src/index.html` | Selects the HTML entry document. Its filename must remain `index.html` |
| `config`      | Project-relative POSIX path | `deno.json`      | Selects the Deno configuration                                         |
| `lockfile`    | Project-relative POSIX path | `deno.lock`      | Selects the frozen Deno lockfile                                       |
| `vite_config` | Project-relative POSIX path | `vite.config.ts` | Selects the Vite configuration                                         |
| `tsconfig`    | Project-relative POSIX path | `tsconfig.json`  | Selects the TypeScript configuration                                   |

## `marimo-studio/notebook-kit`

The Notebook Kit provider builds Observable notebook HTML with Vite and Deno.
Create a view with:

```sh
marimo-studio view create report --target analysis.py \
  --starter marimo-studio/notebook-kit:default
```

Edit `src/index.html` as a Notebook Kit `<notebook>` document. The starter places
eligible Marimo cells in `type="text/html"` cells. `src/page.tmpl` provides the
page shell with `<main id="app-shell">`, and `src/style.css` supplies styling.
Source also includes the live-value and Vite adapters, `vite.config.ts`, `package.json`,
`deno.json`, and the read-only `deno.lock`.

Use all three projection forms inside HTML cells or the page template:

```html
<script id="1" type="text/html">
  <marimo-cell name="controls"></marimo-cell>
  <marimo-output value="summary"></marimo-output>
</script>
<script id="2" type="text/html" output="totalHost">
  <span hidden mo-value="total"></span>
</script>
<script id="3" type="module">
  import { marimoValue } from "./lib/marimo-value.js";
  const total = marimoValue(totalHost);
</script>
<script id="4" type="text/html">
  <p>Total: ${total}</p>
</script>
```

The HTML cell's `output` names its DOM node. `marimoValue(host)` exposes that
host's current and subsequent values to Observable's reactive graph, releasing
its listeners on invalidation. Keep the value host independent of its consumers.
The generator also carries Arrow tables. A terminal projection error stops the
generator and appears in dependent cells. Reload the view after correcting the error.

Literal selectors and conditional expressions with literal branches support
Prepared exports:

```html
<script id="5" type="text/html">
  <marimo-output value="${showDetail ? 'detail' : 'summary'}"></marimo-output>
</script>
```

Define the native control combinations in `states.yaml` when visitors can change
Marimo inputs. See [prepared static exports](../guide/run-and-share.md#export-a-prepared-static-view).
An omitted state file captures the initial notebook state.

For an unbounded runtime selector, use `data-marimo-allow="*"` and the Server or
WebAssembly runtime:

```html
<script id="6" type="text/html">
  <marimo-cell name="${selectedCell}" data-marimo-allow="*"></marimo-cell>
</script>
```

Studio authorizes hosts declared in HTML cells and templates. Put projections
there rather than constructing them in JavaScript strings or Markdown. Native
projections reconnect when Observable replaces an HTML cell.

Keep shared data loading and computation in Marimo. Build-time interpreter cells
and database queries produce diagnostics. Relative `FileAttachment` assets
under `src/` are build inputs. Add exact npm versions to `package.json` and
refresh `deno.lock` when adding browser dependencies. Bare package imports are
bundled. Notebook Kit's `npm:` and `jsr:` imports use remote browser modules.

### Options

| Option        | Type                        | Default          | Contract                                                             |
| ------------- | --------------------------- | ---------------- | -------------------------------------------------------------------- |
| `entrypoint`  | Project-relative POSIX path | `src/index.html` | Selects the notebook document. Its filename must remain `index.html` |
| `config`      | Project-relative POSIX path | `deno.json`      | Selects the Deno configuration                                       |
| `lockfile`    | Project-relative POSIX path | `deno.lock`      | Selects the frozen Deno lockfile                                     |
| `vite_config` | Project-relative POSIX path | `vite.config.ts` | Selects the Vite configuration                                       |

## Deno availability

React, Svelte, and Notebook Kit require the Deno executable packaged by
`marimo-studio[deno]`. Studio requires the pinned Deno version listed in
[Compatibility and support](compatibility.md). `doctor` and `starters` report
an unavailable provider with its recovery action when the executable is
missing or has another version.

Provider builds execute trusted frontend tooling with the current user's
filesystem, environment, and network authority. Review view source and locked
dependencies before building it. See [View provider API](provider-api.md) for
the process and cancellation contract.
