# Report design

A printable worked example for students, lecturers, and analysts. It reads
like a short paper from a numerical optimization course: one argument, told in
order, with two figures and one table that carry the evidence.

## Direction

Classic mathematical typesetting on white A4. New Computer Modern sets the
text and its math companion sets every formula, so prose and notation share
one voice. The figures are the notebook's matplotlib figures, embedded as
vector SVG, and keep the notebook's sans-serif labels. The only color is the
notebook's data red, which marks the solution, the active walls, and their
rows in the wall table. This sets the Report apart from the Explainer's
developer-tool monochrome and the warm textbook pages of the Lecture and Lab.

## Tokens

| Token  | Value     | Use                                               |
| ------ | --------- | ------------------------------------------------- |
| ink    | `#171717` | Text and table rules                              |
| muted  | `#666666` | Captions, the abstract kicker, and the footer     |
| rule   | `#e4e4e4` | The closing hairline                              |
| region | `#eef0f3` | The waiting note                                  |
| data   | `#b33a2e` | Active walls in the wall table                    |

The notebook's `figures` cell draws with the same region fill, level-curve
gray, and solution red, so the figures and the table agree.

## Type

- Title at 22 points with an italic subtitle and a tracked small-caps
  kicker. Numbered section headings in bold at 12 points.
- Justified body text at 10.5 points. Captions at 9 points in muted ink with
  a bold label.
- Numbers use a true minus sign and fixed decimals, and solver residue prints
  as zero.

## Layout

- Page one: title block, abstract, standard form, and the example, with the
  problem figure beside its explanation. The notebook draws it at 4 by 4
  inches, so its labels stay readable in the 228 point column.
- Page two: the solution and wall table, duality, the direction sweep, key
  ideas, and the source attribution above the running footer.
- Tables use booktabs rules: heavy top and bottom, light under the header.
