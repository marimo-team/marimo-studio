# React starter instructions

Follow the `marimo-studio` skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the React project supplied by
this starter.

## Project intent

Compose a three-page A4 facilities brief for building operators and analytical
reviewers from the notebook-owned `occupancy_analysis` snapshot. Page one
states the scope, occupancy rate, daily rhythm, and an operational reading.
Page two compares occupied and vacant sensor conditions and lists the daily
register. Page three explains the occupancy score, shows how accuracy,
precision, and recall move with the threshold, and lists the errors farthest
from the default threshold. Every sentence must stay true for each scope,
including a scope with no occupied readings.

The browser builds the PDF. `src/report/OccupancyReport.tsx` lays the pages out
with [pdfcn](https://github.com/shadcn-labs/pdfcn) components, and
`src/report/render.tsx` renders them to PDF bytes with
[Takumi](https://takumi.kane.tw/docs/pdf), a WebAssembly layout engine that
writes vector PDF. `src/ReportViewer.tsx` paints the same bytes with PDF.js, and
the download link serves them. Mount `analysis_scope_control` beside the
preview so the notebook recomputes every report input from the selected
observations.

`src/pdf/` holds the pdfcn Takumi components copied from the registry, as pdfcn
intends: the project owns them. Keep its `LICENSE` beside them. Local changes
are deliberate: the graph rounds its axis to whole steps and labels fractional
steps with two decimals, the page number keeps the spaces around its counters,
`DataTable` keys its rows directly so striped tables stripe them, and `Section`
honors `noWrap`. `src/report/theme.ts` is the pdfcn theme for the Architect's
Field Report in `DESIGN.md`.

Takumi's WebAssembly module loads from jsDelivr with a pinned version and a
Subresource Integrity digest in `src/report/render.tsx`. Update both together
with the `takumi-pdf` version in `deno.json`. `public/fonts` holds Inter
Regular, Medium, SemiBold, and Bold, subset to Latin text and the symbols the
report uses, with the SIL Open Font License in `OFL.txt`. The report embeds
them, and the workbench uses them for its own text. `public/pdf.worker.min.mjs`
is the PDF.js worker that matches the pinned `pdfjs-dist`.

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
  <section>
    <span ref={hostRef} hidden mo-value="rows" />
    <output>{rows?.numRows ?? 0}</output>
  </section>
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

Studio builds with the frozen `deno.lock`, so builds never change dependencies.
Add a package with one intentional update from the view root. Run the Deno from
`marimo-studio[deno]` through the Python interpreter of the environment that
runs Studio, so the update and later builds use the same Deno. From marimo code
mode, that interpreter is the kernel's `sys.executable`.

```console
python -m deno add --frozen=false --save-exact \
  npm:d3@7 \
  npm:@observablehq/plot@0.6 \
  npm:arquero@8 \
  jsr:@std/csv@1
```

The command updates `deno.json` and `deno.lock` together. Import the aliases it
writes to `deno.json`:

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
`deno.json` and `deno.lock` after adding or changing a dependency.

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

## Load remote font stylesheets

Link remote font stylesheets from `src/index.html` with
`<link rel="stylesheet">`. The Deno CSS bundler cannot load Google Fonts through
CSS `@import`. Linked stylesheets require browser network access and a hosting
policy that permits the stylesheet and font origins. Keep a fallback font in the
view's CSS.

## Link custom results to notebook inputs

Keep projection hosts explicit in authored source. Custom regions need every
kernel input, a readable label, and a rendering-source reference such as
`{"path":"src/App.tsx"}`. Keep these attributes on authored elements outside
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
