---
version: alpha
name: Architect's Field Report
description: An A4 facilities brief for reading room use, environmental separation, and model evidence.
colors:
  paper: "#ffffff"
  ink: "#102126"
  slate: "#3d5761"
  fog: "#677b82"
  mist: "#f1f7f9"
  rule: "#e9eef0"
  signal: "#fa4e1d"
typography:
  display: Inter Medium
  body: Inter
  metadata: Inter Medium
page:
  size: A4 portrait
  count: 3
  margin: 34pt
references:
  - name: Inthememory
    id: 8872694d-261d-4eb4-b355-fb39ee4c37ad
  - name: Kindsight
    id: f22f1195-837d-4b1d-a48c-9123b122bf87
  - name: Firecrawl
    id: 78fec83e-4b27-44ab-9f64-31e9dee53e46
---

## Direction

The report reads like an architect's measured field note. Chalk-white pages,
deep teal type, cool gray rules, and precise diagrams provide the structure. One
ember-orange signal identifies occupied states, selected thresholds, and
evidence that needs attention.

The visual system combines Inthememory's architectural data-room palette,
Kindsight's annual-report hierarchy, and Firecrawl's technical grid discipline.
The browser workbench behaves as quiet document furniture around the report.

## Page system

Each A4 portrait page uses a 34-point horizontal margin and a compact running
header with the page index. Inter carries every role: medium weight with tight
tracking for titles and figures, regular weight for body copy, and tracked
capitals for labels, timestamps, and section coordinates.

Glyphs align to the marks they label. Legend swatches center on their label's
capitals, the dial percentage centers in its ring, error rows center their
text on the score glyph, and section notes share their heading's baseline.

Page one establishes the selected readings, occupancy rate, hourly rhythm, and
operational reading. Page two compares occupied and vacant sensor conditions
and lists the daily register. Page three explains the occupancy score, shows
threshold behavior and classification counts, and lists the errors farthest
from the selected threshold.

The browser workbench places the notebook-owned observation scope between the
document identity and preview. The control names the selected slice while a
compact live readout states how many readings enter the PDF. Changing the
control recomposes the same three-page document in place.

## Workbench

Use a white title rail, hairline dividers, and a compact pale scope row. The
title identifies the room and document. A dark ink pill is the single primary
action. Keep orange for document data and visible keyboard focus.

Render the PDF through PDF.js in every runtime so Server, WebAssembly, and
static delivery share one pale vellum page well. Place the A4 sheets directly
on that surface with a hairline edge and no shadow. The workbench should recede
as soon as the first page is visible.

## Data graphics

Render charts with React PDF's SVG primitives. Occupancy is orange. Model and
CO₂ lines use deep teal and slate. Hairline grids stay cool gray. Use direct
labels and short legends, with scales and comparisons placed beside the values
they explain.

The occupancy dial uses one pale reference track, one orange data arc, and a
direct percentage label. Keep its center open. Remove any chart layer that does
not support a value, comparison, scale, or category.

The environmental schematic uses a top-down room plan. Four labeled leaders
terminate at the room boundary for CO2, light, temperature, and humidity. The
table, chairs, door swing, and occupied position use one consistent plan view.

## Surfaces

Use flat paper, pale mist panels, and hairline borders. Apply modest corner
radii to report panels and a full pill radius to the browser download action.
Keep the report and workbench free of shadows so both retain a printed,
technical character.

The observation scope uses a compact rectangular field tag with tight insets.
Its insets stay proportional to the label so the footprint remains compact.
