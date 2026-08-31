---
version: alpha
name: Blue Field Cinema
description: A one-screen athlete briefing built from a moving point field and sparse editorial captions.
colors:
  canvas: "#060606"
  surface: "#141414"
  on-surface: "#f4f1ea"
  muted: "#9a9ca3"
  line: "#242832"
  primary: "#4490ff"
typography:
  display:
    fontFamily: Barlow Condensed
    fontSize: 104px
    fontWeight: 300
    lineHeight: 0.86
    letterSpacing: -0.035em
  headline:
    fontFamily: Barlow Condensed
    fontSize: 52px
    fontWeight: 300
    lineHeight: 0.94
    letterSpacing: -0.02em
  body:
    fontFamily: Barlow Condensed
    fontSize: 20px
    fontWeight: 400
    lineHeight: 1.35
  label:
    fontFamily: IBM Plex Mono
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0.1em
rounded:
  none: 0px
  control: 2px
spacing:
  unit: 8px
  gutter: 40px
  section: 72px
  container-max: 1600px
components:
  chapter:
    backgroundColor: "transparent"
    textColor: "{colors.on-surface}"
    typography: "{typography.display}"
    rounded: "{rounded.none}"
    padding: 40px
  chrome:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: 16px
  filter:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: 8px
  action:
    backgroundColor: "transparent"
    textColor: "{colors.on-surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: 10px
  divider:
    backgroundColor: "{colors.line}"
    textColor: "{colors.muted}"
    rounded: "{rounded.none}"
    height: 1px
    width: 100%
  progress:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.none}"
    height: 2px
    width: 100%
---

## Overview

The Field is a live briefing for editors, sports researchers, and audiences
looking at the complete Rio roster. A black canvas carries one moving point per
athlete. Sparse captions sit at the edge of the action like film credits. The
visualization remains the dominant surface while Shower keeps the sequence
legible and controllable.

## Colors

Void Black fills the viewport. Chalk carries primary text and athlete marks.
Carbon and Iron separate quiet chrome from the field. Spotlight Blue identifies
medalists, the active view, progress, and focus. Keep blue rare enough that a
single point remains meaningful.

## Typography

Barlow Condensed at weight 300 carries the chapter statements with tight
leading. IBM Plex Mono handles navigation, counts, legends, and controls. The
contrast should resemble a title sequence paired with measured production
notes.

## Layout

The point field fills the viewport. Chapter copy anchors to the lower left and
occupies less than half the desktop width. Persistent navigation sits on the
top edge. Progress and controls sit on the bottom edge. Narrow screens reserve
the upper half for the field and the lower half for copy.

## Elevation & Depth

Three-dimensional depth belongs to the athlete marks. Interface elements stay
flat on the canvas. Hairlines and solid surface changes establish hierarchy.
Cards, shadows, glows, blur, and gradients are outside the visual language.

## Shapes

The visualization uses points, rings, and straight axes. Interface corners are
square or use a 2px radius. Avoid pills and decorative containers. The progress
line is the only continuous edge-to-edge mark.

## Components

The top bar holds the artifact title, sibling views, and load status. Each
chapter contains a compact label, a large statement, one explanatory paragraph,
and a few supporting measures. The sports chapter mounts the native Marimo
filter in one carbon surface. The bottom controls expose previous, next,
fullscreen, and overview behavior. Pointer inspection appears as a small
credit caption beside the field.

## Do's and Don'ts

- Do keep every plotted point tied to a projected athlete row.
- Do compute chapter measures from the current roster.
- Do bring the selected sport to the center and update its projected measures.
- Do preserve keyboard, touch, visible-button, and hash navigation.
- Do use Spotlight Blue for medalists and active state.
- Don't add gradients, purple, soft shadows, glass effects, or rounded cards.
- Don't place explanatory panels over the center of the field.
- Don't animate when the reader requests reduced motion.
