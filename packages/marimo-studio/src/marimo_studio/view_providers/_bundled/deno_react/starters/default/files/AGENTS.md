# React starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the React project supplied by
this starter.

## Project intent

Keep this section current with the user's audience, analytical goal, concrete
project details, aesthetic direction, interaction priorities, and approved
library or framework preferences. Preserve decisions that should guide later
agents.

## Use the supplied Studio integration

The target array mapped to `<marimo-cell>` in `src/App.tsx` starts with each
enabled notebook cell that may display output, including literal Markdown, in
document order. Edit that array and its surrounding JSX to keep, reorder, group,
or replace targets as the component design develops.

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

Use the Deno supplied by `marimo-studio[deno]` in the notebook's Python
environment so dependency updates and Studio builds use the same version.

Run from the view root so it updates `deno.json` and `deno.lock` together:

```console
uv run -- deno add --frozen=false --save-exact \
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
import marimo_studio.agent

print(marimo_studio.agent.skill().file("references/projections.md").read_text())
```

## Maintain project ignore rules

You own this view project's `.gitignore`. When adding libraries, extensions, or
build tools, ignore their generated files, caches, local configuration, and
secrets. Keep authored source, dependency manifests, and lockfiles tracked.
Studio supplies workspace rules for its own artifacts and locks. Check
`git status --short --ignored` after running new tooling and update the view's
ignore rules before committing.
