---
title: Built-in view providers
description: Provider keys, starter IDs, Source documents, requirements, and provider options included with Studio.
---

# Built-in view providers

Studio includes view providers for plain HTML, [React](https://react.dev/),
[Svelte](https://svelte.dev/),
[Observable Notebook Kit](https://observablehq.com/notebook-kit/kit),
[Quarto](https://quarto.org/), [Typst](https://typst.app/), and
[LaTeX](https://www.latex-project.org/). A provider key selects the view
project's inspection and build contract. A starter ID selects the files created
for a new view project.

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

The HTML, React, Svelte, Notebook Kit, and Quarto providers publish web pages
that place notebook results with `<marimo-cell>`, `<marimo-output>`, and
`mo-value` hosts. The Typst and LaTeX providers render their entry document,
such as `main.typ`, to a PDF from the same cells, outputs, and values read
through document functions, and publish a page that shows it.
[Rendered files](projections.md#rendered-files) lists how each runtime supplies
those values.

Source writes preserve the provider key. To change frontend stacks, create
another view with the desired starter. Starter identity is creation input and
stays out of `view.toml`.

## Catalog

| Provider key                 | Starter IDs                                                 | Build requirement        |
| ---------------------------- | ----------------------------------------------------------- | ------------------------ |
| `marimo-studio/vanilla`      | `marimo-studio/vanilla:default`                             | Base Studio installation |
| `marimo-studio/react`        | `marimo-studio/react:default`, `marimo-studio/react:reveal` | `marimo-studio[deno]`    |
| `marimo-studio/svelte`       | `marimo-studio/svelte:default`                              | `marimo-studio[deno]`    |
| `marimo-studio/notebook-kit` | `marimo-studio/notebook-kit:default`                        | `marimo-studio[deno]`    |
| `marimo-studio/quarto`       | `marimo-studio/quarto:default`                              | Quarto 1.9.38 or newer   |
| `marimo-studio/typst`        | `marimo-studio/typst:default`                               | `marimo-studio[typst]`   |
| `marimo-studio/latex`        | `marimo-studio/latex:default`                               | Tectonic 0.15 or newer   |

`marimo-studio starters --json` lists the installed catalog and current
availability. Its `documents` field lists the Source documents a new view
starts with. `view create --dry-run` reports every file Studio will create or
update.

## `marimo-studio/vanilla`

The Vanilla provider publishes browser-native HTML with directly referenced
local CSS and JavaScript. The default starter creates these provider-owned
files, and Studio adds `view.toml` to the project and Source:

```text
AGENTS.md
index.html
```

`index.html` contains one `<marimo-cell>` for each enabled notebook cell that
static inspection determines may display output. `AGENTS.md` describes the
view-authoring contract for a coding agent working in Source.

The starter loads pinned UnoCSS runtime and Iconify Icon web component scripts
from jsDelivr, so authored HTML can use UnoCSS utility classes and
`iconify-icon` elements render named icons. The hosting content security
policy needs `script-src` access to jsDelivr, `connect-src` access to the
configured Iconify API, and `style-src` permission for the inline `<style>`
element UnoCSS generates, which typically requires `'unsafe-inline'`. Use
precompiled project CSS when the policy permits only nonce or hash styles.

The provider adds a directly referenced local stylesheet or script to Source
and the build input set. Keep other local assets inline in the entry document.

Project-relative POSIX paths use forward slashes and start at the view project
root, also on Windows.

### Options

| Option       | Type                        | Default      | Contract                        |
| ------------ | --------------------------- | ------------ | ------------------------------- |
| `entrypoint` | Project-relative POSIX path | `index.html` | Selects the HTML entry document |

Unknown options and paths outside the view project produce a
`provider-options-invalid` diagnostic.

## `marimo-studio/react`

The React provider inspects [TypeScript](https://www.typescriptlang.org/) and
JavaScript source, reports JSX markup that requests notebook results, and
builds an HTML artifact with the pinned [Deno](https://docs.deno.com/)
JavaScript and TypeScript toolchain, with `src/index.html` as the HTML entry
document. `deno.lock` appears in Source as read-only.

### React starter

`marimo-studio/react:default` starts with these Source documents:

```text
AGENTS.md
deno.json
deno.lock
src/App.tsx
src/index.html
src/lib/use-marimo-value.ts
src/main.tsx
src/marimo-studio.d.ts
src/style.css
```

`src/App.tsx` contains one `<marimo-cell>` for each enabled notebook cell that
may display output. `useMarimoValue()` subscribes a React component to a
declared `mo-value` host.

### Reveal.js starter

`marimo-studio/react:reveal` creates a [Reveal.js](https://revealjs.com/) slide
deck with the React starter's project shape and one eligible notebook cell on
each slide.

### Options

| Option     | Type                        | Default        | Contract                                                |
| ---------- | --------------------------- | -------------- | ------------------------------------------------------- |
| `main`     | Project-relative POSIX path | `src/main.tsx` | Selects the React module imported by the entry document |
| `config`   | Project-relative POSIX path | `deno.json`    | Selects the Deno configuration                          |
| `lockfile` | Project-relative POSIX path | `deno.lock`    | Selects the frozen Deno lockfile                        |

## `marimo-studio/svelte`

The Svelte provider inspects Svelte, TypeScript, and JavaScript source, reports
template sites that request notebook results, and builds an HTML artifact with
[Vite](https://vite.dev/), a frontend build tool, through the pinned Deno
toolchain. `deno.lock` and `src/vite-env.d.ts` appear in Source as read-only.

The default starter starts with these Source documents:

```text
AGENTS.md
deno.json
deno.lock
package.json
src/App.svelte
src/app.d.ts
src/index.html
src/lib/marimo-value.ts
src/main.ts
src/style.css
src/vite-env.d.ts
svelte.config.js
tsconfig.json
vite.config.ts
```

`src/App.svelte` contains one `<marimo-cell>` for each enabled notebook cell
that may display output. `observeMarimoValue()` subscribes a Svelte action to a
declared `mo-value` host.

### Options

| Option        | Type                        | Default          | Contract                                                               |
| ------------- | --------------------------- | ---------------- | ---------------------------------------------------------------------- |
| `entrypoint`  | Project-relative POSIX path | `src/index.html` | Selects the HTML entry document. Its filename must remain `index.html` |
| `config`      | Project-relative POSIX path | `deno.json`      | Selects the Deno configuration                                         |
| `lockfile`    | Project-relative POSIX path | `deno.lock`      | Selects the frozen Deno lockfile                                       |
| `vite_config` | Project-relative POSIX path | `vite.config.ts` | Selects the Vite configuration                                         |
| `tsconfig`    | Project-relative POSIX path | `tsconfig.json`  | Selects the TypeScript configuration                                   |

## `marimo-studio/notebook-kit`

The Notebook Kit provider builds Observable notebook HTML with Vite and Deno:

```sh
marimo-studio view create report --target analysis.py \
  --starter marimo-studio/notebook-kit:default
```

`src/index.html` is a Notebook Kit `<notebook>` document, and the starter
places eligible marimo cells in `type="text/html"` cells. `src/page.tmpl`
provides the page shell with `<main id="app-shell">`, and `src/style.css`
supplies styling. Source also includes the live-value and Vite adapters,
`vite.config.ts`, `package.json`, `deno.json`, and the read-only `deno.lock`.

All three projection forms work inside HTML cells and the page template:

```html
<script id="1" type="text/html">
  <marimo-cell name="controls"></marimo-cell>
  <marimo-output value="summary"></marimo-output>
</script>
<script id="2" type="text/html" output="totalHost">
  <span hidden mo-value="total"></span>
</script>
<script id="3" type="module">
  import { marimoValue } from "./lib/marimo-value.js";
  const total = marimoValue(totalHost);
</script>
<script id="4" type="text/html">
  <p>Total: ${total}</p>
</script>
```

The HTML cell's `output` names its DOM node. `marimoValue(host)` exposes the
host's current and subsequent values, including Arrow tables, to Observable's
reactive graph and releases its listeners on invalidation. Keep the value host
independent of its consumers. A terminal projection error stops the generator
and appears in dependent cells. Reload the view after correcting the error.

Literal selectors and conditional expressions with literal branches support
Prepared exports:

```html
<script id="5" type="text/html">
  <marimo-output value="${showDetail ? 'detail' : 'summary'}"></marimo-output>
</script>
```

When visitors can change marimo inputs, define the native control combinations
in `states.yaml`. See
[prepared static exports](../guide/run-and-share.md#export-a-prepared-static-view).
Without a state file, the export captures the initial notebook state.

An unbounded runtime selector needs `data-marimo-allow="*"` and the Python or
Browser runtime:

```html
<script id="6" type="text/html">
  <marimo-cell name="${selectedCell}" data-marimo-allow="*"></marimo-cell>
</script>
```

Studio authorizes hosts declared in HTML cells and templates, so keep
projections there and out of JavaScript strings and Markdown. Native
projections reconnect when Observable replaces an HTML cell.

Keep shared data loading and computation in marimo. Build-time interpreter
cells and database queries produce diagnostics. Relative `FileAttachment`
assets under `src/` are build inputs. Bare package imports are bundled, so add
exact npm versions to `package.json` and refresh `deno.lock` when adding
browser dependencies. Notebook Kit's `npm:` and `jsr:` imports use remote
browser modules.

### Options

| Option        | Type                        | Default          | Contract                                                             |
| ------------- | --------------------------- | ---------------- | -------------------------------------------------------------------- |
| `entrypoint`  | Project-relative POSIX path | `src/index.html` | Selects the notebook document. Its filename must remain `index.html` |
| `config`      | Project-relative POSIX path | `deno.json`      | Selects the Deno configuration                                       |
| `lockfile`    | Project-relative POSIX path | `deno.lock`      | Selects the frozen Deno lockfile                                     |
| `vite_config` | Project-relative POSIX path | `vite.config.ts` | Selects the Vite configuration                                       |

## `marimo-studio/quarto`

The Quarto provider renders a [Quarto](https://quarto.org/) Markdown document
to an HTML page. Quarto turns Markdown with front matter into styled documents
through [Pandoc](https://pandoc.org/). Notebook results enter the page through
the `marimo` [shortcode](https://quarto.org/docs/extensions/shortcodes.html),
which Studio installs as a Quarto extension for each build:

```markdown
---
title: Occupancy
---

Rooms in use today: {{< marimo value="summary.rooms" >}}.

{{< marimo cell="occupancy_chart" >}}
```

::: v-pre

| Shortcode                      | Renders                                          |
| ------------------------------ | ------------------------------------------------ |
| `{{< marimo cell="name" >}}`   | `<marimo-cell name="name">`, a complete cell     |
| `{{< marimo output="name" >}}` | `<marimo-output value="name">`, a value's output |
| `{{< marimo value="path" >}}`  | `<span mo-value="path">`, a JSON value           |

Put a `cell` or `output` shortcode alone on its line with a blank line before
and after it, so the host renders at full width outside a paragraph. Studio
reports `projection-host-inline` for one inside running text. A `value`
shortcode belongs inside a sentence.

An `output` shortcode takes the same
[`accept`](projections.md#rendered-outputs) image list as a `marimo-output`
host, such as `{{< marimo output="chart" accept="image/svg+xml image/png" >}}`.

:::

Raw HTML hosts work in the same documents when a host needs its own element or
attributes, such as `<strong mo-value="summary.rooms"></strong>`. A
`marimo-cell` or `marimo-output` element on its own line with blank lines
around it stays an HTML block. Shortcodes and hosts inside front matter, code,
math, and other shortcodes stay unbound.

The default starter creates these provider-owned files:

```text
AGENTS.md
index.qmd
```

::: v-pre

`index.qmd` contains one `{{< marimo cell="name" >}}` for each enabled notebook
cell that may display output.

:::

The entry document can be `.qmd`, `.md`, or `.markdown`, and Quarto's
[`include`](https://quarto.org/docs/authoring/includes.html) shortcode pulls in
other Markdown files. Studio scans the entry document and every included file
for hosts and lists them in Source. Like Quarto, it resolves an include path
from the entry document's directory, and a path that starts with `/` from the
directory that holds `_quarto.yml`. An include of a missing file reports
`build-input-missing`, and one that leaves the view project reports
`build-input-invalid`.

The provider runs `quarto render --no-execute`, so code chunks stay
unexecuted. Compute in the notebook and project results into the page. Studio
wraps the rendered page body in `<div id="app-shell">`, so authored source must
leave `id="app-shell"` unused.

Every project file is a build input, so a change to an image, include,
stylesheet, or bibliography the document references rebuilds the view.
`view.toml`, `AGENTS.md`, `DESIGN.md`, hidden top-level entries such as
`.gitignore`, the `_site/` and `_freeze/` directories, and the
`<stem>_files/` directory Quarto writes beside the entry document stay outside
the build.

The provider runs the `quarto` command on `PATH`. Install Quarto 1.9.38 or newer
with [pixi](https://pixi.prefix.dev/), a package manager for
[conda-forge](https://conda-forge.org/) packages:

```console
pixi global install quarto
```

`pixi global` puts `quarto` on `PATH` for every way of starting marimo. A pixi
workspace keeps Quarto, Python, and Studio in one project environment, and
`pixi run` starts marimo with that environment activated:

```console
pixi init
pixi add python quarto
pixi add --pypi marimo-studio
pixi run marimo edit analysis.py --no-sandbox --watch
```

conda-forge Quarto finds Pandoc and its resources through environment
activation. Start marimo with `pixi run` or inside `pixi shell`, or `doctor` and
`starters` report Quarto as unavailable. A notebook's pixi script environment
starts unactivated, so Studio takes Quarto from `PATH` for every notebook. The
[Quarto installer](https://quarto.org/docs/get-started/) works as well.

conda-forge Quarto pins its own Deno. In a workspace that also adds
`marimo-studio[deno]` for React, Svelte, or Notebook Kit views, Studio's Deno
replaces it, so install Quarto there with `pixi global install quarto`.

Builds keep Quarto's caches in the `.cache/` directory of the view's build
state, apart from the user cache other Quarto installations share.

On Windows, Quarto keeps a render cache in a SQLite file inside the build
directory, and SQLite opens it only when its path stays under 260 characters.
When a build reports `unable to open database file`, move the notebook to a
shorter directory, such as `C:\work\analysis`.

### Options

| Option       | Type                        | Default     | Contract                                                                  |
| ------------ | --------------------------- | ----------- | ------------------------------------------------------------------------- |
| `entrypoint` | Project-relative POSIX path | `index.qmd` | Selects the Quarto document. It must end in `.qmd`, `.md`, or `.markdown` |

## `marimo-studio/typst`

The Typst provider renders a [Typst](https://typst.app/docs/) document, a
markup-based typesetting format for papers, reports, and slides, to PDF.
Studio renders `main.typ` whenever a notebook value or output it reads changes.
The view page shows the PDF with selectable text and a download link.

```typst
#import "marimo.typ": marimo_output, marimo_value

= Occupancy
Rooms in use: #marimo_value("summary.rooms", default: 0)

#figure(
  marimo_output("occupancy_chart", width: 100%),
  caption: [Rooms in use by hour.],
)
```

The default starter creates these provider-owned files:

```text
AGENTS.md
main.typ
marimo.typ
```

`marimo.typ` defines four functions. Write each selector or name you read
with `marimo_value()`, `marimo_output()`, and `marimo_cell()` as a string
literal so Studio can find what the document reads.

`marimo_value(selector, default: none)` returns the current notebook value for
`selector`, or `default` before the notebook has a value and while the value is
`none`. Values arrive in their
[JSON form](../guide/notebook-results.md#renders-read-json): a pandas,
Polars, or PyArrow table as an array of row dictionaries, and a date or
datetime as ISO 8601 text.

`marimo_output(selector, default: none, ..args)` places a notebook value as an
image with [`image()`](https://typst.app/docs/reference/visualize/image/).
Named arguments such as `width`, `height`, and `alt` pass through to `image()`.
The selector names a notebook variable, so assign the figure to one, such as
`revenue_chart = plot_revenue(rows)`. Studio renders the value in the first of
PDF, SVG, PNG, JPEG, WebP, and GIF that it supports, whatever output settings
the notebook uses. A matplotlib figure or axes arrives as a PDF with embedded
TrueType fonts, so lines stay sharp and text stays selectable. An Altair chart
arrives as a PDF and needs `vl-convert-python` in the notebook's environment,
which the Browser runtime lacks. Other values use their display methods, such
as a PIL image's PNG.

The build compiles the document once and measures the width at which each
`marimo_output()` is placed, resolving `100%` against its container with
[`layout()`](https://typst.app/docs/reference/layout/layout/), and its `height`
when that is an absolute length. `marimo_output("chart", height: 4cm)` records
the height alone. Studio then redraws a matplotlib figure or Altair chart at
that size, so 7-point labels in the notebook print at 7 points. The notebook's
`figsize` sets the aspect ratio. Because it measures its
container, `marimo_output()` places a block.

An output that is unavailable, fails in the notebook, has no image form, or
exceeds the 5,000,000-byte output limit leaves `marimo_output()` at its default,
and the view notes `Showing the default for <selector>.` above the PDF.

`marimo_cell(name, default: none, ..args)` places the output of the notebook
cell called `name` as marimo shows it, when that output is a PDF, SVG, PNG,
JPEG, WebP, or GIF image. A cell that ends with a matplotlib figure arrives as
a PNG. Name the cell in the notebook, for example `def revenue_plot():`. A cell
that has not run, or that shows text or a table, leaves `marimo_cell()` at its
default. Use `marimo_output()` with the figure's variable for a vector PDF.

`marimo_region(..selectors, body, label: none)` marks `body` as the part of
the page that shows the notebook values `selectors` name, such as a table
built from `marimo_value("rows")`:

```typst
#marimo_region("summary.rooms", label: "Rooms in use")[
  Rooms in use: #marimo_value("summary.rooms", default: 0)
]
```

Each selector names a value the document reads, optionally narrowed by
`.field` and `[index]` steps, such as `"rows[0].total"`, and may be computed.
The starter's `main.typ` marks each key figure and table cell this way.

Every render locates each placed output, cell, and region on its PDF page and
returns them as [render regions](provider-api.md#locate-parts-of-rendered-files),
so a reader who selects a figure in the preview sees the notebook cell that
computed it and the line where the document reads it. A region wraps its body
in a [`box`](https://typst.app/docs/reference/layout/box/), which keeps inline
content in its paragraph and keeps the body on one page. Mark the cells of a
long table one by one. The starter's `main.typ` marks the cells of a table's
first 25 rows.

Regions need the `marimo.typ` of the current starter. Copy it into a project
created with an earlier release.

The build compiles the document with every `marimo_value()`,
`marimo_output()`, and `marimo_cell()` call at its default to measure figure
placements. A compile error fails the build at its source line and keeps the
last published view. Each render runs in a child process with a 300 second
deadline.

Renders use Typst's embedded fonts, the font files in the project's `fonts/`
directory, and a compile clock fixed at 1970-01-01, so the same template and
values produce the same PDF on every machine. Pass dates from the notebook in
place of `datetime.today()`. Imports of `@preview` packages download them on
first use and need network access.

`typst compile main.typ` compiles the project outside Studio, where every
`marimo_value()`, `marimo_output()`, and `marimo_cell()` call returns its
default.

Install the Typst compiler with `pip install "marimo-studio[typst]"` in the
environment that runs Studio, or with `pixi add --pypi "marimo-studio[typst]"`
in a pixi workspace.

### Options

| Option       | Type                        | Default    | Contract                                          |
| ------------ | --------------------------- | ---------- | ------------------------------------------------- |
| `entrypoint` | Project-relative POSIX path | `main.typ` | Selects the Typst document. It must end in `.typ` |

## `marimo-studio/latex`

The LaTeX provider typesets a [LaTeX](https://www.latex-project.org/) document
to PDF with [Tectonic](https://tectonic-typesetting.github.io/), a
self-contained TeX engine that downloads the packages a document uses. Studio
renders and shows `main.tex` the same way as a Typst document.

```latex
\documentclass{article}
\usepackage{siunitx}
\usepackage[en-GB, calc]{datetime2}
\usepackage{marimo}

\begin{document}
Rooms in use on \marimodate{summary.day}: \marimonum{summary.rooms}.

\begin{figure}
  \centering
  \marimographics[width=\linewidth]{occupancy_chart}
  \caption{Rooms in use by hour.}
\end{figure}
\end{document}
```

The default starter creates these provider-owned files:

```text
AGENTS.md
main.tex
marimo.sty
```

`marimo.sty` defines the commands that read the notebook. It loads
[siunitx](https://ctan.org/pkg/siunitx), a package that formats numbers and
units, and uses [datetime2](https://ctan.org/pkg/datetime2), a package that
formats dates, when the document loads it. Each command takes a selector, a
notebook variable optionally followed by `.field`, `[index]`, and `["key"]`
steps, written as literal text so Studio can find it:

| Command                                 | Reads                    | Typesets                                                                               |
| --------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------- |
| `\marimovalue[fallback]{selector}`      | Text, number, or boolean | The value as written. Expandable, for titles, bookmarks, and `S` columns               |
| `\marimonum[keys]{selector}`            | A number                 | `\num`, or `\qty` with `unit=`, with the document's siunitx settings                   |
| `\marimodate[style]{selector}`          | A date or datetime       | The date with datetime2's `\DTMdate`, in an optional datetime2 style                   |
| `\marimotime[style]{selector}`          | A datetime or time       | The time with `\DTMtime`                                                               |
| `\IfMarimoTF{selector}{true}{false}`    | Any value                | `false` for null, a missing value, false, zero, and empty text, lists, or dictionaries |
| `\marimorows[count]{selector}{row}`     | A list or table          | `row` for each item, between the rows of a table                                       |
| `\marimoforeach[count]{selector}{body}` | A list or table          | `body` for each item, anywhere else                                                    |
| `\marimographics[keys]{selector}`       | A figure or chart        | The output with `\includegraphics`, drawn at the size it is placed at                  |
| `\marimocell[keys]{name}`               | A named cell's output    | The output as marimo shows it, when it is an image                                     |
| `\marimoregion[label]{selectors}{body}` | Values the body shows    | The body in a box, marked as the part of the page that shows those values              |

Every render locates each `\marimographics`, `\marimocell`, and
`\marimoregion` on its PDF page and returns them as
[render regions](provider-api.md#locate-parts-of-rendered-files), so a reader
can select a figure or a marked value in the preview and follow it to the
notebook cell that computed it. `\marimoregion` takes comma-separated
selectors that the document reads, optionally narrowed with `.field` and
`[index]` steps, and keeps its body on one line, as `\mbox` does. Place it
outside `\scalebox`, `\resizebox`, and `\rotatebox`, which move the body on
the page after `marimo.sty` measures it. Regions need the `marimo.sty` of the
current starter. Copy it into a project created with an earlier release.

`\IfMarimoT` and `\IfMarimoF` take one branch. Inside `\marimorows` and
`\marimoforeach`, `#1` is the item's selector and `#2` its position from 1, so
`\marimovalue{#1.name}` reads a column of the current row, and `count` limits
the items. Values arrive in their
[JSON form](../guide/notebook-results.md#renders-read-json), so a pandas,
Polars, or PyArrow table repeats one row per table row and a date arrives as
ISO 8601 text that `\marimodate` formats.

`\marimonum` takes siunitx keys and four of its own: `scale=` multiplies the
number, `unit=` sets it with `\qty`, and `null=` and `missing=` replace the
text for a null value and for a value Studio has not supplied.
`\DeclareMarimoFormat{name}{keys}` names a set of keys, such as
`\DeclareMarimoFormat{share}{scale=100, round-precision=1, round-mode=places,
unit=\percent}`, read with `\marimonum[share]{model.accuracy}` or combined with
other keys, such as `\marimonum[share, round-precision=2]{model.accuracy}`. A
null value typesets an em dash, also in math, and a value Studio has not
supplied, such as one whose notebook cell failed, typesets `\textbf{??}`.
`\marimosetup{null=..., missing=...}` changes both. In a heading, a read
becomes the PDF bookmark's raw value, such as `0.988`. `\marimovalue` also
expands inside `\ifnum`, `\csname`, and `\label`, where it needs a plain-text
fallback because `\textbf{??}` cannot expand, such as
`\ifnum\marimovalue[0]{summary.days}>1`.

Studio escapes text values, so `50%`, `°C`, and `–` print as written in T1 and
Unicode fonts, link targets in `\href` stay intact, and math symbols such as
`α` keep their character in PDF bookmarks. A read of the wrong kind fails at
its line, such as `report is a dictionary, and \marimovalue reads text,
numbers, and booleans.` Studio supplies exactly the selectors the project's
`.tex` files read, so a selector that a macro builds, such as
`\newcommand\pct[1]{\marimonum{#1}}`, fails with `is not among the values
Studio supplied`, in `\IfMarimoTF` too. The same error names a selector that a
running head uppercased. The scan skips comments, `\verb`, `\lstinline`,
verbatim environments, and `\url`, which prints its argument as written, and
reads commands inside the URL of `\href`. Studio never supplies an argument
with a macro parameter, such as `#1`, because it is computed.

The build compiles the document once without values, and `\marimographics`
logs the width at which it is placed, such as `\columnwidth`, and the height
when `width=` and `height=` both give one. `height=` alone logs only the
height. As with Typst, Studio redraws each
matplotlib figure or Altair chart at that size, and the ink reaches the edges
of that width. Otherwise the notebook's `figsize` sets the aspect ratio. With `keepaspectratio`, `height=` caps the
height, and a figure taller than the cap shrinks with its text. `scale=`,
`angle=` written before `width=`, and a cap that shrinks the figure resize its
text, so `\marimographics` warns about them. An output placed
without `width=`, `height=`, or `scale=` takes the line width. A figure inside
a branch that needs a value, such as the true branch of `\IfMarimoTF`, is
measured only when the build reaches it, so place figures outside such
branches. Studio renders an output in the first of PDF, PNG, and JPEG that the
value supports, with matplotlib figures and Altair charts as PDF like in Typst.
Until an output is available, a frame of the placed `width` and `height` stands
in for it.

Tectonic runs the [XeTeX](https://tug.org/xetex/) Unicode TeX engine and
[BibTeX](https://www.bibtex.org/), which builds the bibliography, and reruns
them until references settle. It compiles in untrusted mode, so shell escape is
off and packages that run programs, such as
[minted](https://ctan.org/pkg/minted), are unavailable. The document itself is
trusted view source, and TeX reads and writes files with the user's authority,
so review a view before building it. A class that checks for pdfTeX with
`\ifpdf` takes its other branch, so when a figure goes missing, declare
graphics extensions in the preamble, for example
`\DeclareGraphicsExtensions{.pdf,.png,.jpg}`. The compile clock is fixed at
1970-01-01, and the Tectonic version pins its package bundle, so the same
template and values produce the same PDF on every machine with that version.
Read dates from the notebook with `\marimodate` in place of `\today`.

The build compiles the document within its 120 second budget, so Tectonic
downloads the packages it uses there, and each later render has a 300 second
deadline. The first compile on a machine needs network access and can take a
few minutes. When it outlasts the build, the build reports
`latex-compile-unfinished`, and the next build continues from the packages
Tectonic kept. To download them without a time limit, run
`tectonic -X compile main.tex` once in the view project. A document that never
finishes compiling, such as one with a recursive macro, reports the same code.
A compile error fails the build at its source line and names the text where TeX
stopped. Undefined references and citations, duplicate labels, missing
characters, overfull boxes wider than a point, and BibTeX errors appear as
warnings above the PDF.

`tectonic -X compile main.tex` or [latexmk](https://ctan.org/pkg/latexmk), a
LaTeX build driver, compiles the project outside Studio, where every read
typesets its fallback.

The provider runs Tectonic 0.15 or newer. A standalone notebook can declare it
for [pixi](https://pixi.prefix.dev/) in its `# /// script` metadata:

```console
pixi add --script analysis.py tectonic
```

Studio then runs the `tectonic` in the notebook's pixi script environment,
before any on `PATH`, when marimo runs the notebook with `--sandbox=pixi` and
in Studio commands that target the notebook. Studio installs that environment
with `pixi install --script`, the command marimo runs before it starts the
kernel, and installs it again after the notebook's dependencies change. When
pixi cannot install it, availability names pixi's error.

`pixi global install tectonic` puts Tectonic on `PATH` for every notebook. In
a pixi workspace, `pixi add tectonic` keeps Tectonic beside Python and Studio.
The [Tectonic installers](https://tectonic-typesetting.github.io/) work as
well.

### Options

| Option       | Type                        | Default    | Contract                                          |
| ------------ | --------------------------- | ---------- | ------------------------------------------------- |
| `entrypoint` | Project-relative POSIX path | `main.tex` | Selects the LaTeX document. It must end in `.tex` |

## Deno availability

React, Svelte, and Notebook Kit require the Deno executable that
`marimo-studio[deno]` packages, at the pinned version listed in
[Compatibility and support](compatibility.md). When the executable is missing
or has another version, `doctor` and `starters` report the provider as
unavailable with its recovery action.

Provider builds run trusted frontend tooling with the current user's
filesystem, environment, and network authority. Review view source and locked
dependencies before building. [View provider API](provider-api.md) describes
the process and cancellation contract.
