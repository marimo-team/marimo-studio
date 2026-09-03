---
version: beta
name: Interactive Earthquake Lesson
description: An editorial academic slide system for linked seismic evidence and live notebook experiments.
colors:
  canvas: "#f2efe7"
  paper: "#fbfaf6"
  on-surface: "#142024"
  body: "#344247"
  muted: "#687477"
  line: "#d4d7d2"
  primary: "#2f5ed8"
  alert: "#df6241"
  context: "#668178"
  night: "#10191b"
typography:
  display:
    fontFamily: Newsreader
    fontSize: 98px
    fontWeight: 500
    lineHeight: 0.91
    letterSpacing: -0.055em
  headline:
    fontFamily: Newsreader
    fontSize: 62px
    fontWeight: 500
    lineHeight: 0.98
    letterSpacing: -0.042em
  body:
    fontFamily: Hanken Grotesk
    fontSize: 20px
    fontWeight: 400
    lineHeight: 1.48
  label:
    fontFamily: SFMono-Regular
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0.105em
rounded:
  control: 2px
  frame: 0px
spacing:
  slide-gutter: 76px
  block-gap: 28px
components:
  slide:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body}"
    padding: 58px
  lab:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.control}"
    padding: 32px
  annotation:
    textColor: "{colors.alert}"
    typography: "{typography.label}"
---

## Decision

The Briefing view is a seven-slide academic lesson built from one fixed USGS
weekly catalog. It teaches catalog provenance, temporal comparison,
logarithmic magnitude, cumulative frequency, selection, and observed impact.
Each slide states one claim and places the evidence beside that claim.

## Analytical ownership

The notebook computes `seismic_analysis`, the magnitude comparison, the
descriptive frequency–magnitude fit, and the selected point on that fit. The
view formats that analytical value into maps, plots, annotations, and
explanatory cases. The magnitude, event-filter, and frequency-threshold cells
remain native Marimo controls, so Server and WebAssembly delivery run the same
reactive computations.

## Sequence

1. The cover poses three questions over the complete weekly epicenter field.
2. The magnitude lab connects a reference slider to amplitude and energy
   ratios.
3. The catalog filter updates the selected count, summary, and epicenter map.
4. The catalog slide separates the published feed, the numeric threshold, and
   the bounded interpretation window.
5. Reveal Auto-Animate expands the compact temporal view while preserving each
   daily mark.
6. The frequency view compares the observed cumulative count with the fitted
   count at a learner-selected magnitude threshold.
7. A position-encoded scatter plot separates magnitude from felt reports.

## Visual system

Warm paper, near-black ink, cobalt selection, and vermilion annotations form
the palette. Newsreader carries claims and numerical evidence. Hanken Grotesk
carries explanation. Monospaced labels identify sources, axes, and slide
chapters. Whitespace establishes hierarchy. Rules remain inside charts when
they provide a baseline, axis, or quantitative reference.

Daily count labels sit directly above their bar tops, and the shared origin
remains implicit. Grid rules mark quantitative reference levels in the
frequency and impact plots.

The map shows every source record on an Equal Earth projection. Marker area
follows magnitude. The selection slide retains source events as quiet context
and colors the current notebook selection in cobalt. Region labels and one
direct event annotation orient the reader without competing with the event
field.

## Interaction

Reveal provides horizontal navigation, progress, slide numbers, fragments,
Auto-Animate, and overview mode. The slide number sits at the top right while
navigation controls remain at the bottom right. The scale and selection
experiments follow the cover, so learners can change the quantities before the
catalog, time, frequency, and impact sequence explains their relationships.
Each visible control answers a named question and keeps a text summary adjacent
to the changed graphic. The frequency threshold stays inside the fitted
interval so the comparison does not imply an extrapolation.

## Layout constraints

Every slide is authored on a 1440×810 canvas. Reveal scales that 16:9 canvas
uniformly and letterboxes it when the viewport uses another aspect ratio. The
composition, type scale, marker geometry, and spacing remain identical at
1440×1000, 1280×720, and 390×844. Charts expose descriptions and summaries to
assistive technology. Keyboard focus remains visible on native controls and
Reveal navigation.
