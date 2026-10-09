# Quarto starter instructions

Follow the `marimo-studio` skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the
[Quarto](https://quarto.org/) document supplied by this starter. Quarto is a
publishing system that renders Markdown with Pandoc. Studio renders this view
with the Quarto CLI and binds notebook results into the rendered HTML.

## Project intent

Keep this section current with the user's audience, analytical goal, concrete
project details, aesthetic direction, and approved Quarto features. Preserve
decisions that should guide later agents.

## Place notebook results

`index.qmd` starts with one `marimo` shortcode for each enabled notebook cell
that may display output. Keep, reorder, group, or replace them as the document
develops. Their names remain stable Studio targets for the notebook cells.

```markdown
Revenue reached {{< marimo value="metrics.total" >}} this quarter.

{{< marimo cell="summary" >}}

::: {.callout-note}
{{< marimo output="chart" >}}
:::
```

- `cell="name"` places a complete notebook cell, and `output="name"` places
  the cell's rendered output. Put either one alone on its line with blank lines
  around it.
- `value="path"` places a JSON value in running text.
- Raw HTML hosts work too. Use them when the host needs its own element or
  attributes, such as `<strong mo-value="metrics.total"></strong>` or
  `<marimo-cell name="summary"></marimo-cell>` on its own line.
- Shortcodes and hosts inside code blocks, inline code, math, and front matter
  stay unbound. Put them in the document body.

## Split the document

Move sections into `.qmd` or `.md` files and pull them in with
`{{< include _section.qmd >}}` on its own line. Hosts in included files bind
like hosts in `index.qmd`. Quarto resolves an include path from the directory
of `index.qmd`, and a path that starts with `/` from the folder that holds
`_quarto.yml`.

To render a plain Markdown file instead of `index.qmd`, set its path in
`view.toml`:

```toml
[options]
entrypoint = "report.md"
```

## Let the notebook compute

Studio renders this document with `--no-execute`. Keep computation in the
notebook and show its results through hosts. A fenced `{python}` cell here
renders as source code only.

## Use Quarto features

Callouts, columns, tabsets, cross-references, citations, and themes work as in
any Quarto HTML document. Set document options in the YAML front matter or a
`_quarto.yml` beside `index.qmd`. Add images, bibliographies, and
stylesheets to this project. Every file here is a build input, so a change
rebuilds the view, except `AGENTS.md`, `DESIGN.md`, hidden entries such as
`.gitignore`, and Quarto's output in `_site/`, `_freeze/`, and `index_files/`.

Studio wraps the page body in `#app-shell`. Leave that ID to Studio.

## Maintain project ignore rules

You own this view project's `.gitignore`. Ignore files that local Quarto runs
create, such as `.quarto/`, `*_files/`, and rendered `*.html` next to
`index.qmd`. Studio supplies workspace rules for its own artifacts and locks.
