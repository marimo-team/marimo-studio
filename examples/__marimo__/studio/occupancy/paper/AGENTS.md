# LaTeX starter instructions

Follow the `marimo-studio` skill for notebook ownership, view lifecycle, and
validation. This file covers the [LaTeX](https://www.latex-project.org/)
document supplied by this starter. Studio typesets `main.tex` to PDF with
[Tectonic](https://tectonic-typesetting.github.io/), a self-contained TeX
engine, and renders it again whenever a notebook value or figure it reads
changes.

## Project intent

Typeset a short research paper in the IEEE TVCG journal format for analysts
and facilities teams who want the occupancy score argued in print. The paper
profiles when Room 01 is used, compares each sensor while the room is occupied
and vacant, defines the light and CO₂ score, and reports its accuracy, the
threshold tradeoff, and the episodes it misjudges. Every sentence must stay
true for each scope and threshold, including the off-hours scope, which has no
occupied readings. `\ifoccupied` in `main.tex` switches those sentences.

The paper reads the notebook's own results: `scope_summary`, `model_summary`,
`occupancy_parameters`, the `daily_room_profile`, `sensor_profiles`, and
`error_episodes` tables, `daily_occupancy_peak`, and `sensor_separation_peak`,
which is `None` in a scope without occupied readings. `score_baselines` gives
the best accuracy of each signal alone. Its four figures are `room_timeline`,
`occupancy_heatmap`, `sensor_distributions`, and `threshold_figure`. Each figure cell sets the figure's shape and style, and
the paper draws it at the width it places it at. Keep computation in the
notebook, and keep number formats, date styles, units, and labels here, as
`DESIGN.md` describes. `\paperterm` names the scope from
`analysis_scope.value` and each sensor from its `key`, so add a definition in
`main.tex` when the notebook gains a scope or a sensor.

`vgtc.cls`, `abbrv-doi-hyperref.bst`, and `diamondrule.pdf` come unchanged
from the IEEE VGTC TVCG journal template, version 2026.06.26. The class may
not be modified, so adapt it from `main.tex`. Under Tectonic the class takes
its non-pdfTeX branch, so `main.tex` declares the graphics extensions, and the
teaser sets its own caption with `\teasercaption`, because the class drops the
text of a caption outside a float under XeTeX.

## Read notebook values

`marimo.sty` defines the commands that read the notebook. It formats numbers
with [siunitx](https://ctan.org/pkg/siunitx) and dates with
[datetime2](https://ctan.org/pkg/datetime2), whose `calc` option names
weekdays:

```latex
\usepackage{siunitx}
\usepackage[en-GB, calc]{datetime2}
\usepackage{marimo}
\sisetup{group-separator={,}, group-digits=integer}
\DeclareMarimoFormat{share}{scale=100, round-mode=places, round-precision=1,
  unit=\percent}

\section{\marimovalue{summary.title}}
We study \marimonum{summary.readings} readings from
\marimodate{summary.start}, and \marimonum[share]{model.accuracy} are right.
\IfMarimoTF{peak}{The peak is \marimovalue{peak.label}.}{No day peaks.}
```

| Command                                | Reads                    | Typesets                                                                |
| -------------------------------------- | ------------------------ | ----------------------------------------------------------------------- |
| `\marimovalue[fallback]{selector}`     | Text, number, or boolean | The value as written. Expandable, so it works in titles and `S` columns |
| `\marimonum[keys]{selector}`           | A number                 | `\num`, or `\qty` with `unit=`, with the document's siunitx settings   |
| `\marimodate[style]{selector}`         | A date or datetime       | The date with `\DTMdate`, in a datetime2 style                          |
| `\marimotime[style]{selector}`         | A datetime or time       | The wall time with `\DTMtime`                                           |
| `\IfMarimoTF{selector}{true}{false}`   | Any value                | `false` for null, a missing value, false, zero, and empty text, lists, or dictionaries |
| `\marimorows[count]{selector}{row}`    | A list or table          | `row` for each item, between the rows of a table                       |
| `\marimoforeach[count]{selector}{body}` | A list or table         | `body` for each item, anywhere else                                     |
| `\marimographics[keys]{selector}`      | A figure or chart        | The output with `\includegraphics`                                      |
| `\marimocell[keys]{name}`              | A named cell's output    | The output as marimo shows it, when it is an image                      |

- Write each selector as literal text. Studio finds the values a document
  reads from these commands and supplies only those, so a selector built by a
  macro, such as `\newcommand\pct[1]{\marimonum{#1}}`, fails with
  `is not among the values Studio supplied`. Name repeated number settings
  with `\DeclareMarimoFormat{name}{keys}` instead. A document reads at most
  100 distinct selectors.
- A selector names a notebook variable, optionally followed by `.field`,
  `[index]`, and `["key"]` steps, such as `\marimovalue{rows[0].name}` or
  `\marimovalue{sensors["CO2 (ppm)"]}`. Read the notebook's own results. A table arrives as a list of rows, a date as ISO 8601 text such
  as `2015-02-04T09:41:00`, and a step through `None`, such as `peak.label`
  while `peak` is `None`, reads null.
- Null typesets `\textemdash` and a value Studio has not supplied yet
  typesets `\textbf{??}`. Change both with `\marimosetup{null=..., missing=...}`
  or for one read with `\marimovalue[n/a]{peak.label}` or
  `\marimonum[null=--]{rate}`. Outside Studio every read typesets its fallback.
- `\marimovalue` expands to its value, so it also works inside `\ifnum`,
  `\csname`, and `\label`. Give it a plain-text fallback there, such as
  `\ifnum\marimovalue[0]{summary.days}>1`, because `\textbf{??}` cannot
  expand.
- Format numbers with `\marimonum`, because `\marimovalue` prints a number as
  the notebook stores it, such as `0.2123296082524868`. `\marimonum` takes
  siunitx keys, `scale=`, `unit=`, `null=`, `missing=`, and format names,
  such as `\marimonum[share, round-precision=2]{model.accuracy}`. To set
  numbers in the face around them, such as in a sans-serif abstract, add
  `mode=match, reset-text-family=false, reset-text-series=false,
  reset-text-shape=false` to `\sisetup`. Studio escapes text, so `50%`, `°C`,
  and `–` print as written in T1 and Unicode fonts.
- In a heading, a read becomes the PDF bookmark's raw value. A class that sets
  uppercase running heads changes the selector's case, so give such a
  heading a short title without reads, such as `\section[Results]{...}`.
- A read of the wrong kind fails at its line, such as `report is a dictionary,
  and \marimovalue reads text, numbers, and booleans.`

Keep computation in the notebook and presentation here: number formats, date
styles, units, labels, and which rows a table shows.

## Repeat table rows

`\marimorows[count]{selector}{row}` repeats a row of a `tabular`, `tabularx`,
`longtable`, or `array` for each item of a list or table, at most `count`
items. `#1` in the row is the item's selector and `#2` its position from 1, so
`\marimovalue{#1.name}` reads the item's `name` column:

```latex
\begin{tabular}{@{}l r r@{}}
  \toprule
  Day & Readings & Occupied \\
  \midrule
  \marimorows{daily_profile}{%
    \marimodate{#1.day} & \marimonum{#1.readings}
    & \marimonum[share]{#1.occupancy_rate} \\}
  \bottomrule
\end{tabular}
```

Place `\marimorows` between two rows of a table, and end the row with `\\`. A
missing, null, or empty list adds no rows, so write the rule above the rows as
`\IfMarimoT{daily_profile}{\midrule}` when the list can be empty. tabularray's `tblr` splits its rows
before it expands commands, so it reports `Misplaced \noalign` there. Use
`tabular`, `tabularx`, `longtable`, or `array`.

`\marimoforeach` repeats its body outside tables, such as the items of a list.
Inside a nested loop, or inside a `\newcommand` body, write the inner loop's
parameters as `##1` and `##2`. Without values a list has no items, so guard an
environment that needs one, such as
`\IfMarimoT{findings}{\begin{itemize}\marimoforeach{findings}{\item ...}\end{itemize}}`.

The build compiles the document without values, so it typesets no rows and
checks no row body. Check a render with notebook values, such as the view's
preview, after changing a row.

A datetime2 style other than the language's own, such as a short weekday
with the day and month, needs a definition in the preamble:

```latex
\DTMnewdatestyle{shortday}{\renewcommand*\DTMdisplaydate[4]{%
  \DTMshortweekdayname{##4} \number##3\ \DTMshortmonthname{##2}}%
  \renewcommand*\DTMDisplaydate{\DTMdisplaydate}}
```

Then `\marimodate[shortday]{#1.day}` prints `Wed 4 Feb`.

## Place notebook figures

Draw charts in the notebook, assign each to a variable, and place it with
`\marimographics`, which takes the options of `\includegraphics`:

```latex
\begin{figure}[t]
  \centering
  \marimographics[width=\linewidth]{revenue_chart}
  \caption{Revenue by quarter.}
\end{figure}
```

- Studio's build compiles the document once and measures where each figure
  is placed. It then draws the matplotlib figure or Altair chart again at that
  width, and at that height when `width=` and `height=` both give one, so its
  text keeps the point size the notebook set, and its ink reaches the edges of
  that width. Otherwise the figure keeps the aspect ratio its `figsize` sets.
  With `keepaspectratio`, `height=` caps the height, and a figure taller than
  the cap shrinks with its text. `height=` alone, `scale=`, `angle=` written
  before `width=`, and a cap that shrinks the figure resize its text, and
  Studio warns about them.
- A matplotlib figure arrives as a PDF with embedded TrueType fonts, and an
  Altair chart as a PDF that needs `vl-convert-python` in the notebook's
  environment. Other values arrive as PDF, PNG, or JPEG when they display as
  one, such as a PIL image. An output placed without `width=`, `height=`, or
  `scale=` takes the line width.
- A figure inside a branch that needs a notebook value, such as the true
  branch of `\IfMarimoTF`, is measured only when the build reaches it. Place
  figures outside such branches so they arrive at their width.
- Until the output is available, a frame of the given `width` and `height`
  stands in for it, with a 16:9 shape without `height`.

## Place notebook cells

`\marimocell[options]{name}` places a named notebook cell's output as marimo
shows it, when that output is an image, such as a cell that ends with a
matplotlib figure. Name the cell in the notebook, for example
`def revenue_plot():`. The output arrives as marimo shows it, typically a PNG
at screen resolution, so prefer `\marimographics` with the figure's variable
in print.

## Write the document

Use any LaTeX class and package. Tectonic downloads the packages a document
uses on its first compile and keeps them, so that compile needs network
access and can outlast a build, which then reports `latex-compile-unfinished`.
Build the view again to continue, or run `tectonic -X compile main.tex` once in
this folder to download the packages without a time limit. Add images,
bibliographies, classes, and more `.tex` files to this project. Every file here
is a build input except `AGENTS.md`, `DESIGN.md`, and hidden entries such as
`.gitignore`.

Tectonic runs the XeTeX engine and BibTeX, and reruns them until references
settle. It compiles with shell escape off, so packages that run programs, such
as `minted`, are unavailable. A class that checks for pdfTeX with `\ifpdf`
takes its other branch, so declare graphics extensions in the preamble when a
figure goes missing, for example
`\DeclareGraphicsExtensions{.pdf,.png,.jpg}`. Overfull boxes wider than a
point appear as warnings, because a value that grows can push a line into the
margin.

The compile clock is fixed at 1970-01-01, so `\today` prints that date. Read a
date from the notebook instead, such as `report_date = date.today()` read with
`\marimodate{report_date}`.

The project also compiles outside Studio with `tectonic -X compile main.tex`
or `latexmk`. Every read then typesets its fallback.
