---
version: alpha
name: Botanical Instrument Panel
description: A calm environmental monitor for facilities staff scanning one room over time.
colors:
  canvas: "#fcfcf7"
  surface: "#ffffff"
  surface-muted: "#eeeee9"
  on-surface: "#1c3a13"
  primary: "#1c3a13"
  muted: "#687164"
  line: "#c4c7c4"
  signal: "#d3fa99"
  chart: "#1c3a13"
  baseline: "#8a9385"
  anomaly: "#546b43"
typography:
  display:
    fontFamily: DM Sans
    fontSize: 64px
    fontWeight: 400
    lineHeight: 0.98
    letterSpacing: -0.035em
  headline:
    fontFamily: DM Sans
    fontSize: 24px
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: -0.02em
  body:
    fontFamily: DM Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: IBM Plex Mono
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0.08em
  data:
    fontFamily: IBM Plex Mono
    fontSize: 34px
    fontWeight: 500
    lineHeight: 1
rounded:
  input: 8px
  card: 16px
  large: 32px
  full: 9999px
spacing:
  unit: 8px
  gutter: 24px
  section: 64px
  container-max: 1216px
components:
  status:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.primary}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: 12px
  metric:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.data}"
    rounded: "{rounded.card}"
    padding: 20px
  chart-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.large}"
    padding: 24px
---

## Overview

The Monitor supports facilities staff who check room conditions, change the
physical signal, and spot anomaly candidates. It should feel like a botanical
laboratory at dawn: warm parchment, deep forest ink, soft clinical surfaces,
and one lime status signal.

## Colors

Warm Parchment is the canvas. Forest Canopy carries text, chart lines, controls,
and borders. Lime Sprout is scarce and marks live status or the selected signal.
Muted stone supports secondary text. Anomalies use a darker olive mark instead
of introducing another hue.

## Typography

DM Sans uses lighter display weights and compact tracking for calm authority.
IBM Plex Mono labels readings, units, dates, and instrument metadata. Numeric
values use tabular figures.

## Layout

Use a centered single-room work area. The header pairs the room identity with a
compact status capsule. The signal control occupies one full-width instrument
band. Four metrics form a row, followed by one dominant chart vessel.

## Elevation & Depth

The system is flat and unshadowed. Parchment, white, and pale stone establish
surface depth. Hairline forest borders define the chart and control boundaries.

## Shapes

Inputs use 8px corners, metric cards use 16px, and the chart vessel uses 32px.
Status and small instrument labels may use a full pill radius.

## Motion

Loading indicators may pulse while notebook values connect. Under
`prefers-reduced-motion: reduce`, stop the pulses and transitions, keep loading
indicators visible at a fixed opacity, and render ECharts updates with zero
animation duration.

## Components

The status capsule uses lime on forest text. Metrics are separate soft cards
with mono numerals. The ECharts line is Forest Canopy, the baseline is muted
sage, and anomaly dots are olive with a parchment edge.

## Do's and Don'ts

- Do keep the chart as the dominant working surface.
- Do use lime as a small status signal.
- Do preserve quiet labels, tabular numbers, and warm neutral spacing.
- Don't use gradients, purple, bright semantic palettes, or card shadows.
- Don't increase display weights above 500.
