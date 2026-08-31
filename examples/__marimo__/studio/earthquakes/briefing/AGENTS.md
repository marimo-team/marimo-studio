# Reveal.js React starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the Reveal.js project supplied
by this starter.

## Project intent

Build a six-slide weekly seismic situation update for a duty-team handover.
Follow the Seismic Proof Sheet in `DESIGN.md`: an achromatic Chronicle-style
grid with color confined to data. Keep one operational claim or decision per
slide and retain `scrollActivationWidth: 0` for Studio's isolated frame.

## Compose the deck

`src/App.tsx` owns the `Deck`, projection subscriptions, and ordered slide
component list. Keep the argument readable as cover, executive assessment,
weekly rhythm, operating picture, priority watchlist, and duty handover.
`src/components/BriefingSlides.tsx` owns those six slide components.
`src/components/BriefingPrimitives.tsx` owns repeated metrics and rhythm bars.
`src/briefing-data.ts` owns projected value types and pure display formatting.

`src/App.tsx` mounts `event_controls` and `conclusion`, then observes
`weekly_summary`, `event_summary`, `daily_activity`, and
`strongest_events`. Place the selected `event_summary` metrics immediately
after `event_controls` so the active review cut is visible on the same slide.

Use Reveal Auto-Animate between the executive assessment and weekly rhythm
slides. Give the pair the same `autoAnimateId`, then keep stable `data-id`
attributes on the rhythm heading, chart, columns, and bars. The compact chart
must expand into the detailed chart while preserving the same data marks.

Use `div` or `article` for semantic regions inside a `Slide`. Reveal treats a
nested `section` as a vertical slide and creates a full-frame background for
it. Use `Stack` when the deck intentionally needs vertical navigation.

Pass Reveal configuration through `Deck.config`. Register plugins through
`Deck.plugins` when the deck first mounts. Keep the plugin array stable because
Reveal initializes plugins once for each deck instance.

Keep `scrollActivationWidth: 0` in the deck configuration. Reveal's automatic
narrow scroll view reads `sessionStorage`, which is unavailable inside Studio's
isolated presentation frame. Slide mode scales to narrow frames and remains
available in Server, WebAssembly, and static delivery.

Use percentage width and height in `Deck.config` so the authored slide grid
owns its available frame at every viewport. Keep every visible element inside
the current slide at 1440×1000, 1280×720, and 390×844. Measure the present
section and its visible descendants in the browser. Repair the layout when any
edge crosses the section bounds or the section scroll size exceeds its client
size.

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
</Slide>
```

Use `src/lib/use-marimo-value.ts` when a React component consumes a notebook
value or eager dataframe:

```tsx
import { type MarimoTable, useMarimoValue } from "./lib/use-marimo-value.ts";

type Row = { region: string; revenue: number };

const { hostRef, value: rows } =
  useMarimoValue<MarimoTable<Row>>("regional_rows");

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
keyboard and control navigation, the Auto-Animate transition, notebook results,
slide numbering, and narrow viewport behavior. Exercise the event controls and
confirm that the selected metrics and handover note react in the same browser
session. The Studio build verifies types and packages the deck before
publishing it.
