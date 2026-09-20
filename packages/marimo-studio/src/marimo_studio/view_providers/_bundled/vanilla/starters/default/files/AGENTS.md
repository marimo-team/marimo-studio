# HTML starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the browser-native project
supplied by this starter.

## Project intent

Keep this section current with the user's audience, analytical goal, concrete
project details, aesthetic direction, interaction priorities, and approved
library or framework preferences. Preserve decisions that should guide later
agents.

## Use the supplied Studio integration

`index.html` starts with one `<marimo-cell>` host for each enabled notebook cell
that may display output, including literal Markdown. Keep, reorder, group, or
replace those hosts as the page design develops. Their generated names remain
stable Studio targets for the notebook cells.

The starter defines `observeMarimoValue` inside the `index.html` module script.
Keep it inline or move it to a JavaScript file referenced directly from the
entry document. Use it when page JavaScript consumes a notebook value or eager
dataframe. Keep the corresponding `mo-value` host in authored HTML so Studio
can inspect and authorize its selector.

```html
<span id="rows-data" hidden mo-value="rows"></span>
```

```js
const source = document.querySelector("#rows-data");
if (source) {
  const stop = observeMarimoValue(source, {
    onValue: (rows) => renderRows(rows),
    onError: (error) => renderError(error.message),
  });
  window.addEventListener("pagehide", stop, { once: true });
}
```

Eager dataframes arrive as a shared Flechette `Table`. Use
[https://github.com/uwdata/flechette](https://github.com/uwdata/flechette) as
the table API reference. Treat the table as immutable. Keep data columnar with
`getChild()`, `select()`, and `toColumns()`. Call `toArray()` when browser code
needs row objects.

## Add dependencies

Import browser-ready ESM modules at the top of the module script. Prefer a
versioned URL for maintained project source:

```js
import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7/+esm";
```

Choose the URL form that matches the dependency source:

- Latest npm release for deliberate experiments:
  `import * as d3 from "https://cdn.jsdelivr.net/npm/d3/+esm";`
- Versioned npm package:
  `import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7/+esm";`
- Concise statistical charts:
  `import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";`
- Tabular transformation:
  `import * as aq from "https://cdn.jsdelivr.net/npm/arquero@8/+esm";`
- Modular charting from an exported package subpath:
  `import * as echarts from "https://cdn.jsdelivr.net/npm/echarts@6/core/+esm";`
- CSV parsing from JSR through esm.sh:
  `import { parse as parseCsv } from "https://esm.sh/jsr/@std/csv";`

Remote modules require browser network access and a hosting content security
policy that allows the selected CDN. Keep all dependency origins explicit and
prefer versioned imports when the same source must rebuild consistently.

## Work within the HTML project

- Keep the document structure and projection hosts in `index.html`.
- Keep styles and browser behavior inline for a compact page, or reference CSS
  through `<link rel="stylesheet">` and JavaScript through `<script src>`
  directly from `index.html`. Studio copies these exact `.css`, `.js`, and
  `.mjs` source files into the browser artifact.
- Keep each direct source as a leaf file. Bundle or inline local CSS `url()` and
  `@import` dependencies and local JavaScript imports or re-exports. Explicit
  HTTPS, data, and fragment references remain available.
- Leave `<base href>` out of the entry document. HTTP and HTTPS dependency URLs
  need `//` and a host.
- Choose a provider that builds the JavaScript module graph for import maps,
  computed imports, and source-phase imports.
- Keep direct JavaScript within the pinned parser's accepted grammar. Inspection
  fails closed when it cannot establish the dependency boundary.
- End `break` and `continue` with `;` when another statement follows. The pinned
  grammar rejects a following regex statement when automatic semicolon
  insertion separates it from the restricted statement.
- The pinned grammar rejects import attributes on re-export statements. Import
  the remote module with its attributes, then use
  `export { value as default }` to preserve a default re-export. Enumerate named
  exports or choose a graph-building provider for a wildcard re-export.
- Keep projection hosts inside `#app-shell`.
- Inline project-owned images and fonts with the document. External HTTP URLs
  and `data:` URLs remain available.
- Use browser APIs for focused interaction. Choose the React or Svelte starter
  when the page needs component compilation, a local import graph, or separate
  browser assets.

Studio publishes the entry document and its declared local sources after
validating the HTML and projection hosts. Treat the built artifact as the
acceptance boundary for the page.

## Preserve notebook traceability

Prefer `mo-value` for values, `marimo-output` for rich values, and `marimo-cell`
for native cell output. Keep analytical computation in the notebook. When custom
JavaScript rendering is necessary, every result must declare its kernel inputs:

- Place hidden `mo-value` hosts directly inside the result, or use
  `data-marimo-lens-inputs="rows-data summary-data"` to reference projection hosts
  by unique, stable HTML IDs in the same document. Include every input,
  including shared inputs used through JS transforms. References must point
  directly to mounted `mo-value`, `marimo-output`, or `marimo-cell` hosts.
  Missing or duplicate IDs make the result unavailable to Lens. Never fabricate
  runtime metadata.
- Annotate individual metrics, rows, charts, and report pages. Prefer narrow
  selectors such as `summary.events`. Bind dynamic selectors and source IDs to
  the state that renders the result. Use `data-marimo-allow="*"` for selectors
  the provider cannot bound at build time. Unbounded selectors require Python or
  Browser runtime (`--runtime wasm` for export). Prepared exports need finite
  authored targets.
- Link browser-only aggregates to their actual kernel inputs and label the
  browser calculation. Canvas and PDF picking is limited to the chart or page
  unless the renderer supplies finer DOM targets.
- Set `aria-busy="true"` during asynchronous rendering and clear it on
  completion. Verify selection and producer context after data updates. These
  links declare dependencies, not automatic JS dataflow or historical values.
- Studio supplies native projection labels. Give custom regions a
  `data-marimo-lens-label` and optional `data-marimo-lens-detail`. Display text
  supplements the source links that connect results to the analytical graph.

## Maintain project ignore rules

You own this view project's `.gitignore`. When adding libraries, extensions, or
build tools, ignore their generated files, caches, local configuration, and
secrets. Keep authored source, dependency manifests, and lockfiles tracked.
Studio supplies workspace rules for its own artifacts and locks. Check
`git status --short --ignored` after running new tooling and update the view's
ignore rules before committing.
