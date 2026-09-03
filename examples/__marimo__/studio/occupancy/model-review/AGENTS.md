# React starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the React project supplied by
this starter.

## Project intent

Build a concise model-review page for analysts and facilities managers. Use
Recharts for the threshold curve, mount the native `analysis_scope_control` and
`threshold_control` cells, and consume the notebook-owned
`occupancy_analysis` snapshot. Keep the page readable as a printable review
artifact. Follow the Parchment Evidence Ledger in `DESIGN.md`, and label the
threshold metrics as in-sample training evidence.

## Use the supplied Studio integration

`src/App.tsx` mounts `analysis_scope_control` and `threshold_control`, then
observes `occupancy_analysis`. React owns the scope readout, threshold chart,
confusion counts, and error-evidence table.

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

When the page needs another package, run Deno's package manager from the view
root so it updates `deno.json` and `deno.lock` together:

```console
deno add --frozen=false --save-exact REGISTRY:PACKAGE@VERSION
```

Replace `REGISTRY`, `PACKAGE`, and `VERSION` with the exact dependency required
by the page. Import the alias written to `deno.json`. Deno accepts registry
package subpaths and explicit local aliases when a package's documentation calls
for them.

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
