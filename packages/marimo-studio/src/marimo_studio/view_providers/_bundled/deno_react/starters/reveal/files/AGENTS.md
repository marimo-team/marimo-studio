# Reveal.js React starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the Reveal.js project supplied
by this starter.

## Project intent

Keep this section current with the audience, presentation goal, concrete project
details, visual direction, interaction priorities, and approved libraries.
Preserve decisions that should guide later agents.

## Compose the deck

`src/App.tsx` owns the `Deck` and its ordered `Slide`, `Stack`, and `Fragment`
children. Keep one audience claim or decision per slide. Use React components
for repeated layouts and local interaction.

The target records mapped to `<Slide>` in `src/App.tsx` start with one record
for each enabled cell that may display output, including literal Markdown. A
Markdown heading supplies its slide label. Edit those records and their
surrounding JSX to keep, reorder, group, or replace slides as the presentation
argument develops.

Pass Reveal configuration through `Deck.config`. Register plugins through
`Deck.plugins` when the deck first mounts. Keep the plugin array stable because
Reveal initializes plugins once for each deck instance.

Keep `scrollActivationWidth: 0` in the deck configuration. Reveal's automatic
narrow scroll view reads `sessionStorage`, which is unavailable inside Studio's
isolated presentation frame. Slide mode scales to narrow frames and remains
available in Server, WebAssembly, and static delivery.

Import `reveal.js/reveal.css` for the structural styles. Keep the deck's visual
system in `src/style.css`, including typography, spacing, colors, controls, and
progress treatment. Preserve full-height sizing for `html`, `body`,
`#app-shell`, and `.reveal`.

## Place notebook results on slides

`src/marimo-studio.d.ts` types the Studio custom elements and attributes. Keep
its reference at the top of `src/App.tsx`.

Place a cell or output directly inside a `Slide` after selecting a target from
the notebook:

```tsx
<Slide>
  <h2>Regional performance</h2>
  <marimo-output value="regional_chart" />
</Slide>;
```

Use `src/lib/use-marimo-value.ts` when a React component consumes a notebook
value or eager dataframe:

```tsx
import { type MarimoTable, useMarimoValue } from "./lib/use-marimo-value.ts";

type Row = { region: string; revenue: number };

const { hostRef, value: rows } = useMarimoValue<MarimoTable<Row>>(
  "regional_rows",
);

return (
  <Slide>
    <span ref={hostRef} hidden mo-value="regional_rows" />
    <strong>{rows?.numRows ?? 0} regions</strong>
  </Slide>
);
```

Keep every projection host in authored TSX so Studio can inspect and authorize
its target. Treat `MarimoTable` as immutable. Use `getChild()`, `select()`, and
`toColumns()` for columnar work, and call `toArray()` when a component needs row
objects.

## Add dependencies

Run Deno's package manager from the view root so it updates `deno.json` and
`deno.lock` together:

```console
deno add --frozen=false --save-exact npm:reveal.js@6.0.1
```

Keep `minimumDependencyAge` and the frozen lockfile policy intact. Commit both
files after an intentional dependency update.

## Validate the presentation

Build through Marimo Studio, then inspect the rendered deck in a browser. Check
keyboard and control navigation, slide scaling, fragments, notebook results,
speaker-facing content, and narrow viewport behavior. The Studio build verifies
types and packages the deck before publishing it.

## Preserve notebook traceability

Prefer `mo-value` for values, `marimo-output` for rich values, and `marimo-cell`
for native cell output. Keep analytical computation in the notebook. When custom
JavaScript rendering is necessary, every result must declare its kernel inputs:

- Place hidden `mo-value` hosts directly inside the result, or use
  `data-marimo-sources="rows-data summary-data"` to reference projection hosts
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
