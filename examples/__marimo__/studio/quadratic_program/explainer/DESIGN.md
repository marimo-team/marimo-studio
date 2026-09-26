# Explainer design

A reading page for students, lecturers, and analysts who want to understand a
quadratic program by changing it. The prose explains one idea at a time while
the figure and the solution stay in view.

## Direction

Monochrome and precise, like a well-made developer tool. Typography, alignment,
and spacing carry the structure on a white canvas, with hairlines only inside
tables. Controls stay black. The only color is the notebook's data red, which
marks the solution and its active walls in the figures and the dual-value
table. This sets the Explainer apart from the warm textbook pages of the
Lecture and Lab.

## Tokens

| Token | Value     | Use                                                   |
| ----- | --------- | ----------------------------------------------------- |
| paper | `#ffffff` | Page background                                       |
| ink   | `#171717` | Text, controls, and active dual rows                  |
| muted | `#666666` | Secondary text, labels, and inactive dual rows        |
| rule  | `#ebebeb` | Table hairlines                                       |
| data  | `#b33a2e` | The notebook's solution color, reused for active rows |

The notebook's figures draw on a transparent background with their own ink,
accent, region, and level colors. Keep `data` aligned with the notebook's
accent.

## Type

- Everything in Geist: semibold headings with tight tracking, regular text,
  sentence-case labels.
- Math: the notebook's rendered notation.
- Values: tabular figures so digits align while controls change.

## Layout

- Wide screens: the reading column on the left, the interactive figure and its
  results sticky on the right.
- Narrow screens: one column that opens with the controls and figure, followed
  by the reading.
