---
version: alpha
name: Seismic Proof Sheet
description: A monochrome operational briefing system for duty handovers and projector-scale data.
colors:
  canvas: "#ffffff"
  surface: "#f3f3f3"
  on-surface: "#050505"
  body: "#292929"
  muted: "#6b6b6b"
  line: "#e2e2e2"
  disabled: "#929292"
  primary: "#1265d8"
  alert: "#c84f32"
typography:
  display:
    fontFamily: Manrope
    fontSize: 76px
    fontWeight: 500
    lineHeight: 0.96
    letterSpacing: -0.045em
  headline:
    fontFamily: Manrope
    fontSize: 48px
    fontWeight: 500
    lineHeight: 1.02
    letterSpacing: -0.035em
  body:
    fontFamily: Manrope
    fontSize: 20px
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: IBM Plex Mono
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0.08em
  data:
    fontFamily: Manrope
    fontSize: 56px
    fontWeight: 500
    lineHeight: 1
    letterSpacing: -0.04em
rounded:
  control: 4px
  frame: 8px
spacing:
  unit: 8px
  slide-gutter: 64px
  block-gap: 32px
  content-max: 1212px
components:
  slide:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.primary}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: 64px
  metric:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.data}"
    rounded: "{rounded.frame}"
    padding: 24px
  control-frame:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.frame}"
    padding: 24px
---

## Overview

The Briefing is a weekly seismic situation update for an operational handover.
It uses the precision of a typographer's proof sheet: a white canvas,
mechanically tight headlines, a strict grid, and color confined to the data
being discussed. Scale, pacing, and consequence signals take priority over
density.

## Colors

The deck chrome is achromatic. Black carries claims, warm gray separates
working surfaces, and hairline gray defines frames. Electric Blue belongs to
data bars and selected values. Clay Red is reserved for an error alert or
tsunami callout.

## Typography

Manrope approximates Chronicle's tightly set Diatype voice. Display and headline
weights stop at 500. IBM Plex Mono labels the slide sequence, filters, dates,
and small data annotations.

## Layout

Every slide uses a fixed proof-sheet grid with generous outer margins. The cover
sets the reporting period and handover context. Working slides align the
operational claim at top left and place controls, metrics, bars, or events in
one bounded frame. The operating-picture slide keeps reactive metrics directly
after the controls that change them.

## Elevation & Depth

Alternate white and warm-gray fields to pace the deck. Cards use a 1px hairline
and one soft neutral shadow when placed on gray. Data on white stays flat.

## Shapes

Controls use 4px corners. Large content frames use 8px corners. The deck avoids
pill geometry so the slide grid remains sharp and editorial.

## Components

Metrics sit in an equal grid with oversized numerals. The activity chart uses
blue bars and a clay peak marker. Reveal Auto-Animate expands the compact
executive rhythm into the detailed daily chart using stable data identities.
Event rows align magnitude, place, and consequence as three columns. Reveal
controls and slide numbers remain small and restrained.

## Do's and Don'ts

- Do keep one audience claim per slide.
- Do let typography and whitespace carry the stage presence.
- Do reserve blue for rendered data and current selection.
- Do keep every visible element inside the slide frame at projector and phone sizes.
- Do use Auto-Animate to preserve identity between the two rhythm views.
- Don't use gradients, purple fields, glass effects, or oversized decoration.
- Don't use more than one visual frame on a slide.
