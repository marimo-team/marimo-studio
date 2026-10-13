# React starter instructions

Follow the `marimo-studio` skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the React project supplied by
this starter.

## Project intent

Build a responsive earthquake operations map for analysts. Use React Map GL with
MapLibre as the primary dependency. Mount the native `event_controls` cell,
consume `filtered_events` and `event_summary`, and keep map hover and selection
local to React. Follow the Midnight Seismic Console in `DESIGN.md`, combining
Mapbox darkness with Linear-style instrument density and one blue active signal.

## Use the supplied Studio integration

`src/App.tsx` mounts `event_controls` and observes `filtered_events` and
`event_summary`. React owns map selection, priority-event selection, and the
selected-event detail panel.

- `src/marimo-studio.d.ts` types the Studio custom elements and attributes for
  React. Keep the reference at the top of `src/App.tsx`. Extend application
  types in a separate declaration when the page introduces its own elements.
- `src/lib/use-marimo-value.ts` adapts an explicit `mo-value` host into React
  state. Keep the host in JSX so Studio can inspect and authorize its selector.

```tsx
import { type MarimoTable, useMarimoValue } from "./lib/use-marimo-value.ts";

type Row = { id: string; label: string };

const { hostRef, value: rows } = useMarimoValue<MarimoTable<Row>>("rows");

return (
  <>
    <span ref={hostRef} hidden mo-value="rows" />
    <output>{rows?.numRows ?? 0}</output>
  </>
);
```

Use the supplied declarations as the type contract. A custom-element type error
indicates a missing declaration reference or an invalid attribute.

Eager dataframes arrive as a shared `MarimoTable` backed by Flechette. Use
[https://github.com/uwdata/flechette](https://github.com/uwdata/flechette) as
the table API reference. Keep data columnar with `getChild()`, `select()`, and
`toColumns()`. Call `toArray()` when a component needs row objects.

Treat the table as immutable. `getMarimoDataSource(table)` returns its codec,
fingerprint, and shared Arrow IPC bytes. Copy the bytes before mutating them.

## Add dependencies

Run Deno's package manager from the view root so it updates `deno.json` and
`deno.lock` together:

```console
deno add --frozen=false --save-exact \
  npm:d3@7 \
  npm:@observablehq/plot@0.6 \
  npm:arquero@8 \
  jsr:@std/csv@1
```

Import the aliases written to `deno.json`:

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

Keep `minimumDependencyAge` and the frozen lockfile policy intact. Commit both
`deno.json` and `deno.lock` after adding or changing a dependency. Use
`--frozen=false` for that intentional update. Normal builds remain frozen.

## Work within the React project

- Build with the React 19 and Deno versions pinned in `deno.json` and
  `deno.lock`.
- Keep the application entry in `src/main.tsx` and compose page components from
  `src/App.tsx` or focused modules under `src/`.
- Keep page styles in `src/style.css` or local CSS modules imported by the
  component that owns them.
- Put static files under `public/` and reference them from the page. The
  provider copies that directory into the built artifact.
- Prefer React state and browser APIs already available in the project.

Studio's React build runs type checking before bundling. Treat that build as the
acceptance boundary for declarations, imports, and packaged assets.

## Visual direction

Keep the presentation calm and focused on the data. Use the current view CSS
as the visual baseline: restrained headings, readable labels, neutral surfaces,
fine borders, and color for selection or analytical meaning. Preserve the
view's distinct audience and interaction model. Check phone, tablet, desktop,
and short landscape layouts, including populated controls and long values.
