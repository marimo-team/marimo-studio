# Reveal.js React view instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the Reveal.js project in the
`briefing` view.

## Project intent

Build the seven-slide interactive earthquake lesson described in `DESIGN.md`. The deck
teaches one scientific argument from a fixed USGS weekly catalog. Place the
magnitude and selection experiments directly after the cover, then develop the
catalog, time, frequency, and impact sequence. Keep one claim and one dominant
evidence frame per slide.

## Compose the deck

`src/App.tsx` owns the `Deck`, the `seismic_analysis` subscription, Reveal
plugins, and the ordered slide list. `src/components/BriefingSlides.tsx` owns
the seven lesson slides. `src/components/BriefingPrimitives.tsx` owns repeated
metrics and the daily activity view.
`src/components/BriefingVisuals.tsx` owns the epicenter field,
frequency–magnitude plot, and magnitude-to-impact scatter plot.
`src/briefing-data.ts` owns projected value types and pure display formatting.

The deck mounts `magnitude_reference_control`, `magnitude_comparison`,
`event_controls`, `frequency_threshold_control`, and
`frequency_magnitude_relation` as native notebook cells. Keep `seismic_analysis`
as the atomic JSON projection so the charts and readouts receive one coherent
notebook revision. Keep slide-specific teaching copy in `BriefingSlides.tsx`.

## Use Reveal

Keep `scrollActivationWidth: 0` in the deck configuration. Reveal's automatic
narrow scroll view reads `sessionStorage`, which is unavailable inside Studio's
isolated presentation frame.

Use the same `autoAnimateId` and stable `data-id` attributes on the catalog and
time slides. Daily bars and maximum-magnitude marks should expand while
preserving visual identity. Use fragments to pace the record-to-evidence
sequence.

Use `div`, `article`, and `aside` for regions inside a `Slide`. Reveal treats a
nested `section` as a vertical slide. Introduce a `Stack` when vertical
navigation is an explicit part of the lesson.

Set `Deck.config` to `width: 1440` and `height: 810`. Reveal scales the fixed
16:9 canvas uniformly inside the available Studio presentation area. Keep slide
geometry in fixed units and avoid viewport breakpoints that reflow the authored
composition. Preserve full-height sizing for `html`, `body`, `#app-shell`, and
`.reveal`.

Place Reveal's slide number at the top right and its navigation controls at the
bottom right. Keep visible slide copy focused on scientific questions,
quantities, methods, and evidence. Put implementation guidance in this file or
`DESIGN.md`.

## Preserve the scientific contract

The notebook owns equations, thresholds, fitted values, summaries, and event
membership. View code may format and arrange projected records. Keep the
frequency–magnitude fit described as a seven-day global teaching example. Keep
magnitude and felt reports as distinct measures. Map labels identify
epicenters and source records, not tectonic boundaries.

## Validate the presentation

Build through Marimo Studio. Export the WebAssembly site and exercise all three
Marimo controls in the browser. Check horizontal navigation, fragments,
Auto-Animate, overview mode, progress, slide numbering, and keyboard focus.

Measure the present slide and its visible descendants at 1440×1000, 1280×720,
and 390×844. Confirm the rendered slide retains a 16:9 ratio and the same
internal geometry at each size. Repair any boundary crossing or scroll
overflow. Inspect every slide after fonts and notebook cells finish loading,
then confirm the selected count, map marks, frequency marker, and magnitude
ratios update from the same browser session.
