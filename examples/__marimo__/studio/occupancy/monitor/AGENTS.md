# Svelte starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the Svelte project supplied by
this starter.

## Project intent

Build a calm room-operations monitor for facilities staff. Use Svelte and Apache
ECharts for the selected sensor series. Mount the native
`analysis_scope_control` and `metric_control` cells, then consume
`selected_sensor_series`, `occupancy_summary`, and `daily_room_profile`. Follow
the visual direction in `DESIGN.md`: neutral surfaces, slate text, blue sensor
readings, muted amber anomaly markers, and plain status text.

## Use the supplied Studio integration

`src/App.svelte` mounts `analysis_scope_control` and `metric_control`, then
observes `selected_sensor_series`, `occupancy_summary`, and
`daily_room_profile`. ECharts receives the projected series after the notebook
reacts to either control.

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
  hidden
  mo-value="rows"
  use:observeMarimoValue={{
    selector: "rows",
    onValue: (value: MarimoTable<Row>) => {
      rows = value;
    },
  }}
></span>

<output>{rows?.numRows ?? 0}</output>
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

## Visual direction

Keep the presentation calm and focused on the data. Use the current view CSS as
the visual baseline: restrained headings, readable labels, neutral surfaces,
fine borders, and color for selection or analytical meaning. Preserve the view's
distinct audience and interaction model. Check phone, tablet, desktop, and short
landscape layouts, including populated controls and long values.
