---
version: alpha
name: Seismic Broadsheet Atlas
description: A public-facing technical narrative that pairs newspaper authority with a dusk cartographic plate.
colors:
  canvas: "#efefec"
  paper: "#ffffff"
  on-surface: "#171716"
  muted: "#64615b"
  line: "#1d1d1b"
  line-soft: "#c9c6bf"
  primary: "#f25533"
  atlas: "#26351b"
  atlas-elevated: "#334722"
  atlas-text: "#f5f1e8"
  compass: "#dc8c46"
typography:
  display:
    fontFamily: Source Serif 4
    fontSize: 88px
    fontWeight: 400
    lineHeight: 0.92
    letterSpacing: -0.045em
  headline:
    fontFamily: Source Serif 4
    fontSize: 48px
    fontWeight: 500
    lineHeight: 1
    letterSpacing: -0.025em
  body:
    fontFamily: Source Serif 4
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.65
  utility:
    fontFamily: IBM Plex Sans
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.4
  label:
    fontFamily: IBM Plex Mono
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0.1em
rounded:
  none: 0px
  sm: 4px
spacing:
  unit: 8px
  gutter: 32px
  section: 80px
  container-max: 1408px
components:
  story-step:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: 24px
  atlas-panel:
    backgroundColor: "{colors.atlas}"
    textColor: "{colors.atlas-text}"
    rounded: "{rounded.sm}"
    padding: 32px
  signal-label:
    backgroundColor: transparent
    textColor: "{colors.primary}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: 0px
---

## Overview

The Story is read by public audiences, journalists, and educators who need a
clear sequence rather than a control room. It combines the authority of a
technical status broadsheet with the atmosphere of a cartographer's atlas at
dusk. The narrative stays on a concrete paper field while the map reads as a
fold-out plate.

## Colors

Concrete gray is the page canvas. Ink and hairline black rules create editorial
structure. Signal Orange marks the active chapter. The sticky map uses a deep
moss field, pale atlas text, and Amber Compass for the rare highlighted event.

## Typography

Source Serif 4 carries display, headings, and narrative paragraphs. IBM Plex
Sans handles navigation and status copy. IBM Plex Mono identifies step numbers,
counts, and source metadata.

## Layout

Use a wide broadsheet grid with narrative chapters in the left column and a
sticky atlas plate in the right column. The hero has a ruled masthead and an
asymmetric headline block. Mobile keeps the map sticky above each chapter card.

## Elevation & Depth

Paper sections remain flat and ruled. The atlas gains depth through moss tonal
steps and a single hairline edge. Shadows stay absent so the page reads as print.

## Shapes

Narrative surfaces and rules are square. The atlas panel may use a 4px radius,
small enough to resemble a mounted map plate rather than an app card.

## Components

The active step uses a 2px orange rule and full-opacity copy. Inactive steps use
quiet ink. The map header behaves like a figure caption. Source links and event
counts sit in a compact utility footer inside the atlas.

## Do's and Don'ts

- Do use serif typography for every narrative claim.
- Do keep the map as the only dark field in the reading flow.
- Do reserve orange and amber for chapter state and event emphasis.
- Don't use gradients, glass effects, rounded cards, or dashboard chrome.
- Don't let map controls compete with the story sequence.
