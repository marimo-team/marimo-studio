---
version: alpha
name: Parchment Evidence Ledger
description: A printable model-review ledger for analysts comparing threshold behavior and training errors.
colors:
  canvas: "#dbdad7"
  paper: "#ffffff"
  surface-muted: "#e6e4e0"
  on-surface: "#121212"
  muted: "#616161"
  line: "#c9c7c2"
  line-strong: "#18181b"
  primary: "#4b7654"
  data-soft: "#e7f0e7"
  error: "#8a4638"
  error-soft: "#f4e7e2"
typography:
  display:
    fontFamily: Source Serif 4
    fontSize: 72px
    fontWeight: 400
    lineHeight: 0.96
    letterSpacing: -0.025em
  headline:
    fontFamily: Source Serif 4
    fontSize: 32px
    fontWeight: 400
    lineHeight: 1.05
    letterSpacing: -0.015em
  body:
    fontFamily: DM Sans
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0.02em
  label:
    fontFamily: IBM Plex Mono
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0.08em
  data:
    fontFamily: Source Serif 4
    fontSize: 48px
    fontWeight: 400
    lineHeight: 1
rounded:
  input: 8px
  card: 8px
  full: 9999px
spacing:
  unit: 4px
  gutter: 32px
  section: 64px
  container-max: 1184px
components:
  metric:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.on-surface}"
    typography: "{typography.data}"
    rounded: "{rounded.card}"
    padding: 20px
  control:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.full}"
    padding: 16px
  evidence-table:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: 16px
---

## Overview

The Model Review is a printable evidence ledger for analysts and facilities
managers. It should read like a financial broadsheet adapted to evaluation:
warm stone outside, white paper inside, one moss data color, serif claims, and
compact tables that reward close reading.

## Colors

Warm Parchment is the outer canvas and Paper is the review sheet. Ink carries
structure. Moss appears only in chart lines, positive table evidence, and the
current threshold marker. Rust identifies errors. Pale green and clay washes
support the confusion matrix.

## Typography

Source Serif 4 owns the report title, section headings, and large metrics. DM
Sans carries explanatory text with slight positive tracking. IBM Plex Mono is
reserved for section indices, table headers, timestamps, and measurement units.

## Layout

Use one centered paper sheet with a two-column masthead. The threshold control
and four metrics form the opening ledger. The curve and confusion table share a
two-column evidence band, followed by the horizontally scrollable error table.
Print mode retains the same hierarchy on A4 landscape.

## Elevation & Depth

The design is flat. Warm stone, white paper, and engraved hairline rules create
depth. The report sheet has no drop shadow in the normative design.

## Shapes

Cards and tables use 8px corners. The Marimo threshold control may sit in a
pill-shaped working area. Table cells and section rules remain rectilinear.

## Components

Metric values use large serif numerals. The Recharts plot uses moss for all
performance curves with distinct dash and opacity treatments. Error evidence
uses rust labels and a pale clay surface. Tables keep tabular numerals and thin
warm-gray rules.

## Do's and Don'ts

- Do keep the document printable and evidence-first.
- Do use moss inside data contexts and rust inside error contexts.
- Do preserve the serif, sans, and mono role separation.
- Don't use gradients, purple, glass surfaces, or colored shadows.
- Don't use moss for actions, links, or decorative fills.
