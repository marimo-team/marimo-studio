---
version: alpha
name: Athlete Logbook
description: A flat, warm-paper exploration surface for coaches, analysts, and data journalists.
colors:
  canvas: "#f9f8f5"
  surface: "#ffffff"
  on-surface: "#21211f"
  muted: "#64635e"
  line: "#e0e0de"
  line-strong: "#9c9b96"
  primary: "#fc5200"
  link: "#0060d0"
  plot-secondary: "#39434d"
typography:
  display:
    fontFamily: Source Sans 3
    fontSize: 80px
    fontWeight: 700
    lineHeight: 0.92
    letterSpacing: -0.045em
  headline:
    fontFamily: Source Sans 3
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: -0.025em
  body:
    fontFamily: Source Sans 3
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: Source Sans 3
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0.08em
rounded:
  sm: 4px
spacing:
  unit: 8px
  gutter: 24px
  section: 64px
  container-max: 1280px
components:
  score:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.headline}"
    rounded: "{rounded.sm}"
    padding: 20px
  filter-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.sm}"
    padding: 20px
  primary-action:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-surface}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 44px
---

## Overview

The Explorer serves people comparing cohorts, brushing distributions, and
locating individual athletes. It should resemble an athlete's training logbook:
flat warm paper, disciplined black type, and one orange highlighter mark. The
interface is denser and more utilitarian than the Nike report, proving that the
same roster can become a working analytical tool.

## Colors

Warm Linen is the canvas and Paper White lifts filters and plots by one tonal
step. Graphite carries text. Strava Orange marks the active view, the selected
metric, and the reset action. Link Blue remains confined to source links.

## Typography

Source Sans 3 is the single family for display, body, controls, and data labels.
Large headings use a compact 700 weight. Body copy and table text use 400.
Labels use 600 with moderate tracking.

## Layout

Use a centered 1280px work area. The header and score row introduce the data.
A sticky filter column sits beside the main plot stack. Supporting charts share
an equal two-column grid, followed by the full-width roster table. Mobile keeps
the analytical order and releases the sticky filter.

## Elevation & Depth

The page is flat. White surfaces separate from warm linen through hairline
borders. Plot grouping comes from spacing and section rules. Drop shadows are
outside this design language.

## Shapes

All controls, panels, buttons, and table surfaces use a 4px radius. This slight
softness keeps the interface approachable while preserving logbook precision.

## Components

The reset button is the single orange filled action. Filter inputs are white
with a warm-gray border. Score values use large black numerals, with the final
medal-award score in orange. Mosaic plots keep quiet neutral axes and use orange
for the primary mark.

## Do's and Don'ts

- Do keep orange concentrated in selection, reset, and primary chart marks.
- Do keep all analytical surfaces flat and bordered.
- Do preserve linked brushing, table sorting, and Arrow-backed loading states.
- Don't introduce a second saturated chart accent.
- Don't use serif display type, large radii, gradients, or soft card shadows.
