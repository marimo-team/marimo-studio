# Bulletin design

A printed seismic bulletin on a newspaper desk: one argument, told in sections,
with figures that carry the evidence and margin notes that carry the asides. It
shares the Story view's broadsheet palette and type, and trades the Story's
scrolling atlas for the steady rhythm of a long-form article.

## Tokens

| Token   | Value     | Use                                                  |
| ------- | --------- | ---------------------------------------------------- |
| paper   | `#fafaf8` | Page background                                      |
| ink     | `#171716` | Text, rules under the title, and observed points     |
| muted   | `#64615b` | Captions, labels, margin notes, and table heads      |
| line    | `#d9dcd7` | Section rules, table hairlines, and graticules       |
| magma   | `#b45435` | Links, citations, strong events, and the fitted line |
| sulfur  | `#dc8c46` | Daily bars, notebook panels, and warning callouts    |
| sand    | `#f2f1ec` | Notebook result panels and the map's ocean           |

## Type

- Source Serif 4 for the title, headings, and running text. The title is set
  large and tight, the subtitle in italic.
- IBM Plex Sans for figures, captions, tables, callouts, and notebook panels.
- IBM Plex Mono in tracked capitals for labels, the table of contents title,
  and the "From the notebook" marker.

## Layout

- Quarto's article layout with the table of contents on the left and margin
  notes and citations on the right. The epicenter map spans the page column.
- Notebook results sit in sand panels with a sulfur edge and a "From the
  notebook" marker, so readers can tell computed output from authored prose.
  Consecutive cells share one panel.
- The four-number strip below the title block uses hairline dividers and
  tabular figures. It folds into a two-by-two grid on narrow screens.
