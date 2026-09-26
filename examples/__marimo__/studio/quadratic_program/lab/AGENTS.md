# Svelte starter instructions

Follow the `marimo-studio` skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the Svelte project supplied by
this starter.

## Project intent

Keep this section current with the user's audience, analytical goal, concrete
project details, aesthetic direction, interaction priorities, and approved
library or framework preferences. Preserve decisions that should guide later
agents.

- Audience: learners who explore by direct manipulation.
- Goal: show how the optimum moves as the linear term `q` turns, and which walls
  hold it.
- The dial, the value curve, and the wall strips all set one browser-side
  direction. They read the notebook's precomputed `sweep`, so dragging needs no
  Python. Only the native `curvature` control selects a prepared notebook state.
- The lab follows the notebook's `pull_direction` when it changes, and keeps the
  reader's dial otherwise.
- D3 supplies scales and line shapes only. The drawing stays in Svelte markup.

## Use the supplied Studio integration

`src/App.svelte` reads four notebook values through explicit `mo-value` hosts,
`region`, `bowl`, `sweep`, and `pull_direction.value`, and projects the
`curvature` cell. Keep a host for every value the components read, and list its
id in the `data-marimo-lens-inputs` of each region that renders it.

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

Use the Deno supplied by `marimo-studio[deno]` in the notebook's Python
environment so dependency updates and Studio builds use the same version.

Run from the view root. Use `--package-json` so Vite resolves application
dependencies through `package.json` and the installed `node_modules` tree:

```console
uv run -- deno add --package-json --frozen=false --save-exact \
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

## Link custom results to notebook inputs

Keep projection hosts explicit in authored source. Custom regions need every
kernel input, a readable label, and a rendering-source reference such as
`{"path":"src/App.svelte"}`. Keep these attributes on authored elements outside
native output subtrees. Follow the installed Studio skill's
`references/projections.md` for the shared contract:

```python
import marimo_studio

print(marimo_studio.agent.skill().file("references/projections.md").read_text())
```

## Maintain project ignore rules

You own this view project's `.gitignore`. When adding libraries, extensions, or
build tools, ignore their generated files, caches, local configuration, and
secrets. Keep authored source, dependency manifests, and lockfiles tracked.
Studio supplies workspace rules for its own artifacts and locks. Check
`git status --short --ignored` after running new tooling and update the view's
ignore rules before committing.
