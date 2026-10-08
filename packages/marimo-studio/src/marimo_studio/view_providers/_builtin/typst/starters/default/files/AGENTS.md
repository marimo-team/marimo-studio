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
  and dictionaries. Whole floats such as `2.0` arrive as integers.
- Give every call a `default`. A document must compile before the notebook
  has values, and Studio checks that when it builds the view.
- Project tables in the notebook before reading them here, for example
  `rows = df.to_dicts()`. Dataframes are not JSON values.

Keep computation in the notebook and layout here. Prefer one dictionary per
section, such as `report`, over many separate values.

## Place notebook figures

Draw charts in the notebook and place them with `marimo_output()` from
`marimo.typ`. `marimo_output()` places a notebook value as an image, whatever
output settings the notebook uses. A matplotlib figure arrives as a PDF with
selectable text, and an Altair chart as an SVG:

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
  `image()`. Set the figure's size in the notebook, such as
  `figsize=(7, 3.5)`, so its text keeps a readable size at the placed width.
- `marimo_output()` returns its `default`, `none` unless given, until the
  output is available, and when the notebook cell fails, the value has no
  image form, or the image exceeds the runtime output limit. The view names
  such an output beside the document.

## Place notebook cells

`marimo_cell()` places a named notebook cell's output as marimo shows it, when
that output is an image, such as a cell that ends with a matplotlib figure:

```typst
#import "marimo.typ": marimo_cell

#figure(marimo_cell("revenue_plot", width: 100%), caption: [Revenue.])
```

- Name the cell in the notebook, for example `def revenue_plot():` or
  `@app.cell(name="revenue_plot")`.
- The cell's output arrives in the format marimo shows, typically PNG for a
  matplotlib figure. Prefer `marimo_output()` with the figure's variable when a
  vector PDF matters.
- `marimo_cell()` returns its `default` until the cell has run, and when its
  output is text, a table, or another output without an image form.

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
`report_date = date.today().isoformat()` read with
`marimo_value("report_date")`.

The project also compiles outside Studio with `typst compile main.typ`. Every
`marimo_value()` and `marimo_output()` call then returns its default.
