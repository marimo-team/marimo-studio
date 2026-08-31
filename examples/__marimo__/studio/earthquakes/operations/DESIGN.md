---
version: alpha
name: Midnight Seismic Console
description: A dense MapLibre operations surface for incident analysts reviewing a fixed weekly feed.
colors:
  canvas: "#0e1012"
  surface-low: "#15171b"
  surface: "#1c1f24"
  surface-high: "#23262d"
  line: "#333943"
  on-surface: "#ffffff"
  muted: "#a0aaba"
  quiet: "#687383"
  primary: "#0062ca"
  signal-bright: "#007afc"
  warning: "#f3b64c"
  alert: "#ff684f"
  success: "#55d49b"
typography:
  display:
    fontFamily: DM Sans
    fontSize: 64px
    fontWeight: 700
    lineHeight: 0.95
    letterSpacing: -0.035em
  headline:
    fontFamily: DM Sans
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: -0.015em
  body:
    fontFamily: DM Sans
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: IBM Plex Mono
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0.1em
  data:
    fontFamily: IBM Plex Mono
    fontSize: 28px
    fontWeight: 500
    lineHeight: 1
rounded:
  utility: 4px
  control: 6px
  panel: 12px
  full: 9999px
spacing:
  unit: 8px
  panel-gap: 12px
  gutter: 24px
  container-max: 1728px
components:
  metric:
    backgroundColor: "{colors.surface-low}"
    textColor: "{colors.on-surface}"
    typography: "{typography.data}"
    rounded: "{rounded.utility}"
    padding: 16px
  operations-panel:
    backgroundColor: "{colors.surface-low}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.panel}"
    padding: 16px
  active-status:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-surface}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: 8px
---

## Overview

The Operations view supports incident analysts who scan status, filter the
feed, locate an epicenter, and open the USGS record. It should feel like a map
console at midnight: the basemap is the luminous instrument, the surrounding
panels stay quiet, and one blue signal identifies active controls.

## Colors

Layer the page through four near-black surfaces. White belongs to headings and
selected values. Muted blue-gray carries descriptions. Signal Blue identifies
active state and focus. Amber marks major magnitude and coral marks tsunami
flags. Semantic colors stay inside event and status contexts.

## Typography

DM Sans supplies compact geometric headings and readable UI text. IBM Plex Mono
owns counts, timestamps, IDs, labels, and status readouts. Use tabular numerals
for every metric and event fact.

## Layout

Use a wide centered console. The header and metric strip span the full width.
The notebook filter forms a compact command bar. Priority events, map, and event
detail align in a three-column instrument grid. Narrow screens put the map
first, followed by the priority list and detail record.

## Elevation & Depth

Depth comes from stepped dark surfaces and inset hairline borders. Panels may
use one soft black shadow at the outer console boundary. Map media dissolves
into the page through its dark tile palette.

## Shapes

Panels use 12px corners. Utility controls use 4px to 6px corners. Active status
and map filters may use a full pill radius. This contrast separates map-scale
controls from precise data records.

## Components

Metric cells use mono numerals with quiet uppercase labels. Selected priority
events receive a blue inset rule. The event picker and Marimo filter use dark
inputs with a blue focus ring. Map markers keep warm severity colors against
the cool console.

## Do's and Don'ts

- Do let the map occupy most of the workspace.
- Do use blue for active interaction and warm colors for event severity.
- Do keep event lists and facts compact, aligned, and tabular.
- Don't use gradients, bright card fills, decorative borders, or glass blur.
- Don't introduce another accent hue outside semantic event status.
