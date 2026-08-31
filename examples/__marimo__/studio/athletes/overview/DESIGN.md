---
version: alpha
name: Nike Performance Index
description: A high-contrast athletic campaign report for first-time Studio readers.
colors:
  canvas: "#0a0a0a"
  paper: "#f2efe7"
  surface: "#fffef9"
  on-surface: "#0a0a0a"
  inverse-text: "#ffffff"
  muted: "#74746e"
  line: "#262626"
  primary: "#dfff35"
typography:
  display:
    fontFamily: Helvetica Neue
    fontSize: 96px
    fontWeight: 900
    lineHeight: 0.82
    letterSpacing: -0.07em
  headline:
    fontFamily: Helvetica Neue
    fontSize: 56px
    fontWeight: 900
    lineHeight: 0.9
    letterSpacing: -0.05em
  body:
    fontFamily: Avenir Next
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: Helvetica Neue
    fontSize: 11px
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: 0.14em
rounded:
  none: 0px
spacing:
  unit: 8px
  gutter: 32px
  section: 64px
  container-max: 1440px
components:
  hero:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.inverse-text}"
    typography: "{typography.display}"
    rounded: "{rounded.none}"
    padding: 64px
  metric-strip:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-surface}"
    typography: "{typography.headline}"
    rounded: "{rounded.none}"
    padding: 24px
  content-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.none}"
    padding: 24px
---

## Overview

The report is the portfolio's visual anchor. It introduces Studio through the
language of an athletic campaign: compressed scale, hard contrast, a diagonal
motion mark, and one electric signal color. The audience is a reader seeing
notebook projections for the first time, so the page should feel immediate and
confident before it feels analytical.

Keep the existing composition and visual character. The memorable move is the
black hero breaking into the volt metric strip, followed by a quiet paper report.

## Colors

Obsidian and white carry the campaign voice. Warm paper softens the analytical
section. Volt marks computed values, the active view, and small labels. It stays
concentrated in the metric strip and compact signals.

## Typography

Use a condensed, italicized Helvetica-style display treatment for campaign
headlines and metrics. Avenir Next carries explanatory copy and native-control
context. Labels remain uppercase, compact, and widely tracked.

## Layout

The hero spans the viewport width and uses an asymmetric two-column grid. The
metric strip forms a hard horizontal break. The control and native output share
a two-column report band on desktop and stack in reading order on narrow screens.

## Elevation & Depth

The system is flat. Surface changes, 2px rules, and the offset volt edge on the
control create hierarchy. Shadows are reserved for the control's hard campaign
offset.

## Shapes

Use square corners for every report surface, control frame, and table panel.
The diagonal hero mark supplies motion while the component geometry stays rigid.

## Components

The native Marimo control sits in a white framed block with a volt offset. The
native table sits in a bordered paper panel. Metrics use oversized italic
numerals with small uppercase labels.

## Do's and Don'ts

- Do preserve the current hero, volt strip, diagonal mark, and report layout.
- Do keep the direct native control and native output visually obvious.
- Do use volt for computed emphasis and active state.
- Don't add card rounding, soft gradients, or ornamental icons.
- Don't restyle the page toward the sibling Explorer.
