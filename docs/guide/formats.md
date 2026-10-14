---
title: Choose a format
description: Pick a starter for a view, from a plain HTML page or a React or Svelte app to a Quarto document or a Typst or LaTeX PDF.
---

# Choose a format

Every view starts from a starter, which sets its format and its first files.
Pick one in **Add view**, or pass `--starter` to `marimo-studio view create`.

| Starter                              | The view is                                                | Setup                  |
| ------------------------------------ | ---------------------------------------------------------- | ---------------------- |
| `marimo-studio/vanilla:default`      | An HTML page with inline CSS and JavaScript                | None                   |
| `marimo-studio/react:default`        | A React app written in TypeScript                          | `marimo-studio[deno]`  |
| `marimo-studio/react:reveal`         | A [Reveal.js](https://revealjs.com/) slide deck            | `marimo-studio[deno]`  |
| `marimo-studio/svelte:default`       | A Svelte app built with Vite                               | `marimo-studio[deno]`  |
| `marimo-studio/notebook-kit:default` | An Observable notebook of JavaScript and HTML cells        | `marimo-studio[deno]`  |
| `marimo-studio/quarto:default`       | A [Quarto](https://quarto.org/) Markdown document          | Quarto 1.9.38 or newer |
| `marimo-studio/typst:default`        | A PDF typeset with [Typst](https://typst.app/)             | `marimo-studio[typst]` |
| `marimo-studio/latex:default`        | A PDF typeset with [LaTeX](https://www.latex-project.org/) | Tectonic 0.15 or newer |

The first six are pages, so their controls stay live in the browser. Typst
and LaTeX views are documents: Studio compiles a PDF from the notebook's
results and compiles it again when a result it reads changes.

Start with the HTML page when you are unsure. Move to React or Svelte when
components, imported assets, or npm packages make the view easier to
maintain. Choose Typst or LaTeX when the result is a paper or a report to
print or send.

To use a tool that is not listed, install or write a
[view provider](view-providers.md). Its starters appear in **Add view** next to
these.

## HTML

```console
marimo-studio view create report --target analysis.py
```

The starter writes `index.html` and `AGENTS.md`. The page already places every
notebook cell that shows output. It loads pinned
[UnoCSS](https://unocss.dev/) and Iconify Icon scripts from jsDelivr for
utility classes and icons, so the hosting
[Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)
must allow them. [Style a page](styling.md#use-the-html-starter-helpers) lists
the exact directives.

Keep CSS and JavaScript inline, or reference local files directly:

```html
<link rel="stylesheet" href="./style.css" />
<script type="module" src="./main.js"></script>
```

Studio publishes directly referenced `.css`, `.js`, and `.mjs` files as they
are. CSS imports, asset URLs in CSS, and JavaScript module imports need a
bundler, so switch to React or Svelte when a page grows them. Leave
`<base href>` out of the page, because Studio sets it when it publishes.

## React, Svelte, and Notebook Kit

These starters build with [Deno](https://docs.deno.com/), a JavaScript
toolchain that ships on PyPI. Install it in the notebook's Python project:

```console
uv add 'marimo-studio[deno]'
```

Then create the view:

::: code-group

```console [React]
uv run marimo-studio view create operations --target analysis.py \
  --starter marimo-studio/react:default
```

```console [Reveal.js]
uv run marimo-studio view create briefing --target analysis.py \
  --starter marimo-studio/react:reveal
```

```console [Svelte]
uv run marimo-studio view create explorer --target analysis.py \
  --starter marimo-studio/svelte:default
```

```console [Notebook Kit]
uv run marimo-studio view create monitor --target analysis.py \
  --starter marimo-studio/notebook-kit:default
```

:::

- **React** writes TypeScript and JSX, a `useMarimoValue` hook, `deno.json`,
  and a frozen lockfile. Its build type-checks before it bundles.
- **Reveal.js** is a React deck with one starting slide for each notebook cell
  that shows output. Place controls and the results they drive on the same
  slide.
- **Svelte** builds with [Vite](https://vite.dev/) and writes a
  `use:observeMarimoValue` action. Its build runs `svelte-check` first.
- **Notebook Kit** writes [Observable](https://observablehq.com/notebook-kit/kit)
  cells in `src/index.html`. Place hosts inside `type="text/html"` cells, and
  read values into Observable's reactive graph with `marimoValue(host)`.

Add an npm package from the view folder, with the same Deno that Studio uses:

```console
uv run -- deno add --frozen=false --save-exact npm:d3@7
```

Add `--package-json` for Svelte and Notebook Kit, which list dependencies in
`package.json`. Commit the updated lockfile. Studio builds with the lockfile
frozen, so every build resolves the same packages. Outside a uv project, run
`python -m deno` with the Python that runs Studio.

## Quarto

[Quarto](https://quarto.org/) renders Markdown with front matter into a styled
page. Install Quarto 1.9.38 or newer, for example with
`pixi global install quarto`, then create a view:

```console
marimo-studio view create article --target analysis.py \
  --starter marimo-studio/quarto:default
```

Write `index.qmd` and place results with the `marimo` shortcode. Put `cell`
and `output` shortcodes on their own line between blank lines, and `value`
shortcodes inside a sentence:

```markdown
Rooms in use today: {{< marimo value="summary.rooms" >}}.

{{< marimo cell="occupancy_chart" >}}
```

Studio renders with `--no-execute`, so the computation stays in the notebook.
The **Bulletin** view of [Earthquake watch](../examples/earthquakes.md) is a
Quarto article with citations, callouts, and notebook figures.

## Typst

[Typst](https://typst.app/docs/) typesets papers and reports from markup.
Install the compiler in the notebook's Python project, then create a view:

```console
uv add 'marimo-studio[typst]'
uv run marimo-studio view create report --target analysis.py \
  --starter marimo-studio/typst:default
```

`main.typ` imports the starter's `marimo.typ`:

```typst
#import "marimo.typ": marimo_output, marimo_value

Rooms in use: #marimo_value("summary.rooms", default: 0)

#marimo_output("occupancy_chart", width: 100%)
```

Until the notebook supplies a value, `marimo_value()` returns its `default`, so
give each one a default the surrounding markup can format. `marimo_output()`
places nothing until its figure exists. The same file compiles with
`typst compile main.typ` outside Studio, using every default. The **Report**
view of [Quadratic programs](../examples/quadratic-programs.md) is a Typst
report that embeds the notebook's matplotlib figures.

## LaTeX

[LaTeX](https://www.latex-project.org/) typesets papers with any class and
package, such as a journal's submission template. Studio compiles it with
[Tectonic](https://tectonic-typesetting.github.io/), a self-contained TeX
engine:

```console
pixi global install tectonic
marimo-studio view create paper --target analysis.py \
  --starter marimo-studio/latex:default
```

`main.tex` loads the starter's `marimo.sty`:

```latex
\usepackage{siunitx}
\usepackage[en-GB, calc]{datetime2}
\usepackage{marimo}

Rooms in use on \marimodate{summary.day}: \marimonum{summary.rooms}.

\marimographics[width=\linewidth]{occupancy_chart}
```

`\marimonum` formats a number with [siunitx](https://ctan.org/pkg/siunitx),
`\marimodate` a date with [datetime2](https://ctan.org/pkg/datetime2), and
`\marimorows` repeats a table row for each row of a dataframe. A null value
typesets an em dash, a value that has not arrived typesets `??`, and a figure
that has not arrived leaves a frame of its placed size.

The first compile downloads the TeX packages the document uses and can take a
few minutes. The **Journal paper** view of
[Building occupancy](../examples/occupancy.md) is a paper in the IEEE TVCG
journal template with the notebook's figures and tables.

## When documents render

| Where the view runs                                       | Typst and LaTeX views show                          |
| --------------------------------------------------------- | --------------------------------------------------- |
| Studio editor, in any runtime                             | A PDF compiled again when a result it reads changes |
| `marimo run` with the Python runtime                      | A PDF compiled again when a result it reads changes |
| Prepared export                                           | One PDF for each prepared input state               |
| `marimo run` with the Browser runtime, or a `wasm` export | The PDF compiled when the view was built            |

A page can also draw a PDF in the browser from `mo-value` data with a
JavaScript PDF library, which works in every runtime. The **Field report** view
of [Building occupancy](../examples/occupancy.md) does this with
[pdfcn](https://github.com/shadcn-labs/pdfcn).

## List installed starters

```console
marimo-studio starters
```

The list shows each starter's ID, provider, availability, and the setup it
needs. `--json` adds the files each starter creates.
[Built-in view providers](../reference/built-in-providers.md) documents every
starter's files and options.
