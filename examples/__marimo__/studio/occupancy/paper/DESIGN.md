---
version: alpha
name: Journal Paper
description: A TVCG journal paper that argues the occupancy score in print.
colors:
  ink: "#102126"
  slate: "#3d5761"
  fog: "#677b82"
  mist: "#dfe8ec"
  signal: "#fa4e1d"
typography:
  body: Times, from the vgtc class, with newtxmath for mathematics
  captions: Helvetica at 8 points, from the vgtc class
  figures: DejaVu Sans at 7 points
page:
  size: US Letter, two columns
  count: 3
---

## Direction

The paper follows the IEEE TVCG journal template exactly, so it reads as a
submission to a visualization journal. The class owns the page: Times body
text, Helvetica headings and captions, two columns, the abstract block with its
index terms, and the diamond rule. The paper adds only what the class leaves
open: the notebook's figures, booktabs tables, numbers set with `siunitx`, and
dates set with `datetime2`.

## Figures

The four figures are the notebook's matplotlib figures, embedded as vector
PDF with TrueType text. Each figure cell sets its aspect ratio and its 7-point
style, and Studio draws it again at the width the paper places it at: the
abstract block for the teaser, `\columnwidth` for a column, and `\textwidth`
across both columns. Its labels therefore print at 7 points. The figures
share the occupancy family's palette: ink and slate lines, fog axes, mist for
heatmap cells without occupancy, white for hours without readings, and the
ember signal for occupied readings only. Only the left and bottom spines
remain, and value axes carry a faint grid.

## Tables

Tables use booktabs rules at the class's 8-point table size, with units in
the column heads. Numbers align right with a fixed number of decimals, read
with commas between thousands, and shares carry one decimal, with the percent
sign in the column head. A null value, such as an occupied mean in a scope
without occupied readings, prints as an em dash in the table's face.

## Text

Numbers in prose come from the notebook and take the face around them, so the
Helvetica abstract prints Helvetica digits, and a percent sign closes up to its
number. Shares carry one decimal, hours one decimal, counts no decimals, and
the threshold and weights two. Tables put units and percent signs in their
column heads. Dates name the weekday and month in full in prose and in short in
tables, and times use the 24-hour clock without seconds. The paper names the
notebook's scopes and sensors itself, keyed by their notebook keys, and states
the scope in the abstract and in Section 2. Paragraphs never break before their
last line, after their first, or after a hyphen.
