# Svelte starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the Svelte project supplied by
this starter.

## Project intent

Keep this section current with the user's audience, analytical goal, concrete
project details, aesthetic direction, interaction priorities, and approved
library or framework preferences. Preserve decisions that should guide later
agents.

## Use the supplied Studio integration

The target array in the `{#each ... as name}` block in `src/App.svelte` starts
with each enabled notebook cell that may display output, including literal
Markdown, in document order. Edit that array and its surrounding markup to keep,
reorder, group, or replace targets as the component design develops.

- `src/app.d.ts` adds Studio attributes to Svelte's element types.
- `src/lib/marimo-value.ts` supplies the `observeMarimoValue` action. Attach it
  to an explicit `mo-value` host so Studio can inspect and authorize the
  selector.

```svelte
<script lang="ts">
  import {
    type MarimoTable,
    observeMarimoValue,
  } from "./lib/marimo-value.ts";

  type Row = { id: string; label: string };

  let rows = $state<MarimoTable<Row>>();
</script>

<span
  id="rows-data"
  hidden
  mo-value="rows"
  use:observeMarimoValue={{
    selector: "rows",
    onValue: (value: MarimoTable<Row>) => {
      rows = value;
    },
  }}
></span>

<output data-marimo-lens-inputs="rows-data">{rows?.numRows ?? 0}</output>
```

Use the supplied declaration and action as the integration contract. Keep
page-specific value handling in the component that consumes it.

Eager dataframes arrive as a shared `MarimoTable` backed by Flechette. Use
[https://github.com/uwdata/flechette](https://github.com/uwdata/flechette) as
the table API reference. Keep data columnar with `getChild()`, `select()`, and
`toColumns()`. Call `toArray()` when a component needs row objects.

Treat the table as immutable. `getMarimoDataSource(table)` returns its codec,
fingerprint, and shared Arrow IPC bytes. Copy the bytes before mutating them.

## Add dependencies

Run Deno's package manager from the view root. Use `--package-json` so Vite
resolves application dependencies through `package.json` and the installed
`node_modules` tree:

```console
deno add --package-json --frozen=false --save-exact \
  npm:d3@7 \
  npm:@observablehq/plot@0.6 \
  npm:arquero@8 \
  jsr:@std/csv@1
```

Import the package names or explicit alias written to `package.json`:

```ts
import * as d3 from "d3";
import * as Plot from "@observablehq/plot";
import * as aq from "arquero";
import { parse as parseCsv } from "@std/csv";
```

Choose the packages the page actually needs. D3 and Observable Plot render
visualizations, Arquero transforms tabular data, and `@std/csv` parses CSV
through JSR. Deno also accepts registry package subpaths and explicit local
aliases when a package's documentation calls for them.

Keep `minimumDependencyAge` and the frozen lockfile policy intact. Commit
`package.json` and `deno.lock` after adding or changing an application
dependency. Use `--frozen=false` for that intentional update. Normal builds
remain frozen.

## Work within the Svelte project

- Use Svelte 5 runes such as `$state` and `$derived` for local browser state.
- Keep the application entry in `src/main.ts` and compose the page from
  `src/App.svelte` or focused components under `src/`.
- Keep page styles in `src/style.css` or component-owned `<style>` blocks.
- Put static files under `public/` and reference them from the page. Vite copies
  that directory into the built artifact.
- Use the versions pinned by `package.json`, `deno.json`, and `deno.lock`.
  TypeScript source imports may retain their `.ts` suffix.

Studio's Svelte build runs `svelte-check` before Vite. Treat that build as the
acceptance boundary for actions, runes, imports, and packaged assets.

## Preserve notebook traceability

Prefer `mo-value` for values, `marimo-output` for rich values, and `marimo-cell`
for native cell output. Keep analytical computation in the notebook. When custom
JavaScript rendering is necessary, every result must declare its kernel inputs:

- Place hidden `mo-value` hosts directly inside the result, or use
  `data-marimo-lens-inputs="rows-data summary-data"` to reference projection
  hosts by unique, stable HTML IDs in the same document. Include every input,
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
