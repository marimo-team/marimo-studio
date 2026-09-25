# Explainer design

A reading page for students, lecturers, and analysts who want to understand a
quadratic program by changing it. The prose explains one idea at a time while
the figure and the solution stay in view.

## Direction

Quiet and exact, like a well-set textbook page. White space and alignment carry
the structure. One accent marks the solution, and nothing else competes with
it.

## Tokens

| Token  | Value     | Use                                            |
| ------ | --------- | ---------------------------------------------- |
| paper  | `#faf9f6` | Page background                                |
| ink    | `#1b1d22` | Text, primary lines, the bottom of the bowl    |
| muted  | `#6b6f76` | Secondary text and captions                    |
| rule   | `#e5e2dc` | Hairlines and table borders                    |
| accent | `#b33a2e` | The solution, active walls, and contact curves |
| region | `#eef0f3` | The feasible region in the notebook's figures  |
| level  | `#9aa0a8` | Level curves and inactive walls in the figures |

The notebook's figures draw with ink, accent, region, and level. Keep those
colors aligned with the notebook.

## Type

- Headings: Newsreader, regular weight, tight leading.
- Text and controls: Inter.
- Values: tabular figures so digits align while controls change.

## Layout

- Wide screens: the reading column on the left, the interactive figure and its
  results sticky on the right.
- Narrow screens: one column that opens with the controls and figure, followed
  by the reading.
