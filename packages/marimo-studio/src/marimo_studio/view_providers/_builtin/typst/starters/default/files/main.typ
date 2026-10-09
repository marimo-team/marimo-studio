#import "marimo.typ": marimo_value

#let notebook = __NOTEBOOK_LABEL_TYP__
#let title = __VIEW_HEADING_TYP__
#let muted = luma(105)

#set document(title: title)
#set page(
  paper: "a4",
  margin: (x: 2.2cm, y: 2.4cm),
  numbering: "1 / 1",
  header: context if counter(page).get().first() > 1 {
    set text(8pt, fill: muted)
    notebook
    h(1fr)
    title
  },
)
#set text(font: "Libertinus Serif", size: 10.5pt)
#set par(justify: true, leading: 0.68em)
#show heading.where(level: 1): set text(size: 24pt)
#show heading.where(level: 2): it => block(above: 1.8em, below: 0.9em, it)
#show raw: set text(font: "DejaVu Sans Mono", size: 9pt)

// `report` is a notebook variable that holds JSON values. Its scalar fields
// become key figures, and each list of dictionaries becomes a table.
__REPORT_BINDING_TYP__

#let field-name(key) = upper(key.replace("_", " "))

#let show-value(item) = {
  if item == none [—]
  else if type(item) == bool { if item [Yes] else [No] }
  else if type(item) == float { str(calc.round(item, digits: 2)) }
  else if type(item) in (int, str) { str(item) }
  else { repr(item) }
}

#let figures(fields) = grid(
  columns: (1fr,) * calc.min(fields.len(), 3),
  gutter: 14pt,
  ..fields.map(((key, item)) => block(
    width: 100%,
    inset: (top: 8pt),
    stroke: (top: 0.6pt + luma(200)),
  )[
    #text(7.5pt, fill: muted, tracking: 0.06em, field-name(key)) \
    #text(15pt, show-value(item))
  ]),
)

#let records(rows) = {
  let columns = rows.first().keys()
  table(
    columns: (1fr,) * columns.len(),
    stroke: (x, y) => if y == 0 { (bottom: 0.6pt + luma(160)) },
    inset: (x: 6pt, y: 5pt),
    align: (x, y) => if y > 0 and type(rows.at(y - 1).at(columns.at(x), default: none)) in (int, float) {
      right
    } else { left },
    table.header(..columns.map(column => text(8pt, weight: "bold", field-name(column)))),
    ..rows.map(row => columns.map(column => show-value(row.at(column, default: none)))).flatten(),
  )
}

#text(8pt, fill: muted, tracking: 0.08em, upper(notebook))
= #title

#if report == none {
  block(fill: luma(246), inset: 14pt, radius: 3pt, width: 100%)[
    *Connect a notebook value.* Define `report` in the notebook as a
    dictionary of JSON values, and read it in `main.typ`. Studio renders this
    page again whenever the notebook changes it.

    ```python
    report = {"rooms": 12, "occupancy": 0.71, "readings": table}
    ```
  ]
} else {
  let scalars = report.pairs().filter(((key, item)) => type(item) not in (array, dictionary))
  if scalars.len() > 0 { figures(scalars) }
  for (key, item) in report.pairs() {
    if type(item) == array and item.len() > 0 and type(item.first()) == dictionary {
      heading(level: 2, field-name(key))
      records(item)
    } else if type(item) == dictionary and item.len() > 0 {
      heading(level: 2, field-name(key))
      figures(item.pairs())
    }
  }
}
