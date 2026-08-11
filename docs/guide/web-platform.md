---
title: Use HTML, CSS, and JavaScript
description: Author Studio views with standard web documents, browser APIs, modules, components, libraries, and relative assets.
---

# Use HTML, CSS, and JavaScript

A Studio view is a complete HTML document. Use the browser platform for page
structure, responsive layout, visual design, modules, components, and direct
interaction. Studio connects notebook results to that authored document while
the calculations and reactive dependencies remain in Marimo.

## Structure the document

Each `index.html` contains one `#app-shell`:

```html{12} [index.html]
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Revenue dashboard</title>
    <link rel="stylesheet" href="app.css" />
  </head>
  <body>
    <main id="app-shell" class="studio-view grid gap-6">
      <h1>Revenue dashboard</h1>
      <marimo-output value="revenue_chart"></marimo-output>
    </main>
    <script type="module" src="app.js"></script>
  </body>
</html>
```

Place every `<marimo-cell>`, `<marimo-output>`, and `mo-value` host inside
`#app-shell`. Studio can replace the authored shell after a save while the
selected Marimo runtime remains mounted.

## Write responsive CSS

Choose regular CSS in `app.css` or Wind4 utility classes in `index.html`. The
starter file groups shared light and dark tokens under `/* THEME */` and page
rules under `/* APP */`.

::: code-group

```css [app.css]
/* THEME */

:root {
  color-scheme: light dark;
  --background: light-dark(#ffffff, #111713);
  --foreground: light-dark(#17201b, #edf3ef);
  --card: light-dark(#f8faf9, #18201b);
  --card-foreground: var(--foreground);
  --border: light-dark(#dce3df, #344039);
  --primary: light-dark(#0877d1, #3ba7ad);
  --radius: 8px;
}

/* APP */

.summary-grid {
  display: grid;
  gap: 1.5rem;
  grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
}
```

```html [index.html]
<main id="app-shell" class="studio-view grid gap-6 lg:grid-cols-2">
  <section class="studio-card p-5">
    <h2 class="text-lg font-semibold">Revenue</h2>
    <marimo-output value="revenue_chart"></marimo-output>
  </section>
</main>
```

:::

Rules in `app.css` use the regular CSS cascade. Wind4 utility classes cover
responsive layout, spacing, typography, color, borders, and state variants.

Studio provides four stable shortcuts:

| Class            | Behavior                                          |
| ---------------- | ------------------------------------------------- |
| `studio-view`    | Centered page width with responsive outer padding |
| `studio-card`    | Semantic bordered surface                         |
| `studio-button`  | Compact interactive control                       |
| `studio-eyebrow` | Small uppercase section label                     |

The utility vocabulary follows [UnoCSS Wind4](https://unocss.dev/presets/wind4).

## Add modules and assets

Reference JavaScript modules, images, fonts, data, and nested files relative to
their source file:

```html
<img src="images/logo.svg" alt="Acme" />
<script type="module" src="scripts/app.js"></script>
```

```js
import { renderBriefing } from "./render-briefing.js";

renderBriefing(document.querySelector("#briefing"));
```

Relative JavaScript imports and CSS `url(...)` references use the browser's
regular resolution rules. A module save reloads the view document so the
browser evaluates its module graph again.

Use standard browser APIs, SVG, Canvas, Web Components, and existing browser
libraries in these modules.

::: warning Check deployed network policy
Network-loaded modules and assets require the deployed page's content security
policy and network access to permit their origin.
:::

::: warning Treat view scripts as application code
Authored JavaScript runs on the same origin as the Marimo session. Give
source-editing access to people and agents trusted with the notebook, its data,
and its credentials. Review third-party modules before deployment.
:::

## Read notebook data in JavaScript

Use a hidden `mo-value` host as the typed data source for browser behavior:

```html
<span id="report-data" hidden mo-value="report"></span>
<output id="report-total"></output>
<script type="module" src="app.js"></script>
```

::: tip Register before reading the current snapshot
Register the update listener before reading `marimoValue` so an update cannot
arrive between the initial read and listener registration.

```js [app.js]
const source = document.querySelector("#report-data");
const total = document.querySelector("#report-total");

const render = (report) => {
  total.textContent = report.total;
};

source.addEventListener("marimo-value-updated", (event) => {
  render(event.detail.value);
});

if (source.marimoValue !== undefined) {
  render(source.marimoValue);
}
```

:::

`undefined` means the first value has not arrived or the reference is
currently unavailable. JSON `null` remains a value. Listen for
`marimo-value-error` when the component needs a local fallback.

Wait for every current projection when a module coordinates several page
regions:

```js
await window.marimoStudio.ready();
const diagnostics = window.marimoStudio.diagnostics();
```

The [view document reference](../reference/view-document.md) defines property,
event, loading, readiness, and diagnostic behavior.

::: details Load complete cell output on demand

[HTMX](https://htmx.org/) is available as `window.htmx`. Request a configured
cell after a user action:

```html
<button
  type="button"
  hx-get="./_marimo-studio/views/dashboard/cells/detail_table"
  hx-target="#details"
>
  Show details
</button>
<section id="details" aria-live="polite"></section>
```

The response inserts a `<marimo-cell>` host connected to the current Marimo
session.
:::

## Develop beside the notebook

Open the configured notebook in Marimo:

```console
uv run --with marimo-studio marimo edit analysis.py --sandbox
```

The **Build** screen shows the notebook and selected view together. Open
**HTML & CSS** to edit `index.html` and `app.css` in the browser. Saves from the
workspace or an external editor update the same files on disk.

Use the Server preview while developing against the editor's Python kernel.
After each change, inspect controls, tables, plots, downloads, widgets,
loading states, keyboard focus, and narrow and wide layouts.

[Author with the live workspace](live-authoring.md) explains saved layouts,
source conflicts, refresh behavior, runtime comparison, and query state.
Continue with [Agent-native authoring](coding-agents.md) to inspect, edit, and
validate views with a coding agent, or [Run, export, and share](run-and-share.md)
for delivery options.
