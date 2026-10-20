# Typst starter instructions

Follow the `marimo-studio` skill for notebook ownership, view lifecycle, and
validation. This file covers the [Typst](https://typst.app/docs/) document
supplied by this starter. Typst is a markup-based typesetting system. Studio
renders `main.typ` to PDF and renders it again whenever a notebook value or
figure it reads changes.

## Project intent

Keep this section current with the user's audience, analytical goal, page
format, and typographic direction. Preserve decisions that should guide later
agents.

## Read notebook values

`marimo.typ` defines `marimo_value()`. Each call reads one notebook value:

```typst
#import "marimo.typ": marimo_value

#let report = marimo_value("report", default: none)
Total revenue: #marimo_value("metrics.total", default: [—])
```

- Write the selector as a string literal. Studio finds the values a document
  reads from these calls, and supplies only those.
- A selector names a notebook variable, optionally followed by `.field` and
  `[index]` steps, such as `marimo_value("rows[0].name")`.
- Values arrive as JSON: `none`, booleans, integers, floats, strings, arrays,
  and dictionaries. Whole floats such as `2.0` arrive as integers. A pandas,
  Polars, or PyArrow table arrives as an array of row dictionaries, and a
  date, datetime, or time as ISO 8601 text such as `2015-02-04T09:41:00`.
- Give every call a `default`. A document must compile before the notebook
  has values, and Studio checks that when it builds the view. A value that is
  `none`, or a step through `none` such as `peak.label` while `peak` is
  `None`, also returns the `default`.

Keep computation in the notebook and presentation here: read the notebook's
own results, and format numbers, dates, and labels in the document.

## Place notebook figures

Draw charts in the notebook and place them with `marimo_output()` from
`marimo.typ`. `marimo_output()` places a notebook value as an image, whatever
output settings the notebook uses. A matplotlib figure arrives as a PDF with
embedded TrueType text, and an Altair chart as a PDF:

```typst
#import "marimo.typ": marimo_output

#figure(
  marimo_output("revenue_chart", width: 100%),
  caption: [Revenue by quarter.],
)
```

- The selector names a notebook variable that holds a matplotlib figure or
  axes, an Altair chart, or another value that displays as PDF, SVG, PNG,
  JPEG, WebP, or GIF, such as a PIL image. Assign the figure to a variable,
  such as `revenue_chart = plot_revenue(rows)`.
- Altair charts need `vl-convert-python` in the notebook's environment.
- Named arguments such as `width`, `height`, `fit`, and `alt` pass through to
  `image()`. Studio's build measures the width each output is placed at, and
  its absolute `height` when given, then draws a matplotlib figure or Altair
  chart again at that size, so its text keeps the point size the notebook set.
  The notebook's `figsize` sets the aspect ratio. `marimo_output()` measures
  its container with `layout()`, so it places a block.
- `marimo_output()` returns its `default`, `none` unless given, until the
  output is available, and when the notebook cell fails, the value has no
  image form, or the image exceeds the runtime output limit. The view then
  notes `Showing the default for <selector>.` above the PDF.

## Place notebook cells

`marimo_cell()` places a named notebook cell's output as marimo shows it, when
that output is an image, such as a cell that ends with a matplotlib figure:

```typst
#import "marimo.typ": marimo_cell

#figure(marimo_cell("revenue_plot", width: 100%), caption: [Revenue.])
```

- Name the cell in the notebook by its function name, for example
  `def revenue_plot():`.
- The cell's output arrives in the format marimo shows, typically PNG for a
  matplotlib figure. Prefer `marimo_output()` with the figure's variable when a
  vector PDF matters.
- `marimo_cell()` returns its `default` until the cell has run, and when its
  output is text, a table, or another output without an image form.

## Mark traceable parts

Studio locates each `marimo_output()` and `marimo_cell()` on its PDF page, so a
reader can select a figure in the preview with Lens and follow it to the
notebook cell that computed it. Wrap content built from values in
`marimo_region()` to make it selectable as well:

```typst
#import "marimo.typ": marimo_region, marimo_value

#marimo_region("summary.rooms", label: "Rooms in use")[
  Rooms in use: #marimo_value("summary.rooms", default: 0)
]
```

- Each selector names a value the document reads with `marimo_value()`,
  optionally narrowed with `.field` and `[index]` steps, such as
  `"rows[0].total"`. The selector may be computed, as `main.typ` does for each
  table cell.
- A region keeps its body on one page. Mark the cells of a long table one by
  one.

## Write the document

Use any Typst feature: page setup, show rules, tables, figures, bibliographies,
and math. Add images, fonts, data files, and more `.typ` files to this project.
Every file here is a build input except `AGENTS.md`, `DESIGN.md`, and hidden
entries such as `.gitignore`.

Studio compiles with Typst's embedded fonts and the fonts in this project's
`fonts/` directory, so the PDF looks the same on every machine. Add font files
there to use another family. Imports of `@preview` packages download them on
first use and need network access.

The compile clock is fixed at 1970-01-01, so `datetime.today()` returns that
date. Pass dates from the notebook instead, for example
`report_date = date.today()` read with `marimo_value("report_date")` as ISO
8601 text.

The project also compiles outside Studio with `typst compile main.typ`. Every
`marimo_value()` and `marimo_output()` call then returns its default.
