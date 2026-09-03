# React starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the React project supplied by
this starter.

## Project intent

Build a three-page A4 facilities brief for building operators and analytical
reviewers. Compose the notebook-owned `occupancy_analysis` snapshot into the
document. Mount `analysis_scope_control` so the notebook recomputes every
report input from the selected observations. Show the selected scope and
observation count beside the control. Render once with `@react-pdf/renderer`,
then share that PDF blob between the named download and regular browser
preview. Render the same bytes with PDF.js in every runtime so the workbench
keeps one light page well across Server, WebAssembly, and static delivery.

Use native React PDF SVG primitives for charts so the report stays sharp when
printed. Keep each page fixed to A4 portrait, use explicit page composition, and
repeat the report identity and page count through fixed page furniture. Follow
the Architect's Field Report in `DESIGN.md`: chalk paper, deep teal ink,
hairline rules, Newsreader display type, Hanken Grotesk body type, and one
restrained orange signal. Keep the observation scope as a compact field tag
whose insets follow its text.

Keep the environmental graphic in a top-down plan view with labeled signal
leaders. Each line identifies a room boundary, fixture, access path, occupied
position, or sensor channel.

Pin `@react-pdf/renderer` to `4.8.1`, `pdfjs-dist` to `5.4.149`, and `events` to
`3.3.0`. `src/install-node-events.ts` maps the one CommonJS `node:events`
lookup left by Deno's browser bundle to React PDF's browser events dependency.
`public/pdf.worker.min.mjs` is the corresponding PDF.js worker and is copied
into the published artifact.

Resolve the WOFF files under `public/fonts` through
`src/install-report-fonts.ts`, then register the same asset URLs with React PDF
and the browser. The SIL Open Font License files travel with the published
artifact.

The pinned `@fontsource/newsreader` and `@fontsource/hanken-grotesk` packages
own the source files. Run `deno task sync:fonts` after changing their versions
or selected weights, then commit the public fonts and license files together.

## Use the supplied Studio integration

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

Subscribe to `occupancy_analysis` as one projection. It commits the summary,
profiles, sensor comparisons, threshold curve, and ranked errors together so a
reactive change composes one notebook generation.

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
