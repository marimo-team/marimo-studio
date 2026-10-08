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
  rule: "#dfe7ea"
  signal: "#fa4e1d"
typography:
  display: Inter SemiBold
  body: Inter
  metadata: Inter SemiBold
page:
  size: A4 portrait
  count: 3
  margin: 40pt
---

## Direction

The report reads like an architect's measured field note built from shadcn-style
document components. White pages, deep teal type, cool gray rules, and flat
mist panels provide the structure. One ember-orange signal identifies occupied
states, the busiest day, the most separating sensor, and evidence that needs
attention.

## Page system

Each A4 portrait page uses 40-point side margins and a running footer with the
room, the report name, and the page count. Page one opens with pdfcn's
two-column page header and scope badges. Every page starts with a numbered
orange kicker, such as `02 / SENSOR CONDITIONS`, above a semibold heading and a
muted lede.

Page one establishes the readings, occupancy share, estimated occupied time, and
score accuracy in four metric cards with an ink or orange edge, then the daily
occupancy chart, the occupied-to-vacant donut, and three findings. Page two
tabulates the sensor comparison, charts separation and daily CO₂ side by side,
and closes with the daily register. Page three pairs the score formula with the
confusion counts, charts accuracy, precision, and recall by threshold, and lists
the errors farthest from the threshold.

## Data graphics

Charts are pdfcn graphs drawn in vector form. Occupancy and the occupied mean
are orange, everything else uses slate and ink. Axes round to whole steps.
Single-series charts carry no legend, and values sit on the bars they label.

## Workbench

The browser workbench is quiet document furniture: a white title rail, a pale
scope strip with the notebook's scope control and the reading count, and a
vellum well where PDF.js paints the A4 sheets with a hairline edge. A dark ink
pill is the single primary action, Download PDF.
