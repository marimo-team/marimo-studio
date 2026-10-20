---
title: Select results with Lens
description: Point at any part of a Studio view, from a placed cell to a figure inside a PDF, and hand it to a coding agent with the notebook cell that computed it.
---

# Select results with Lens

[marimo-lens](https://github.com/marimo-team/marimo-lens) is a marimo widget
that lets you select part of a rendered result and hand it to a coding agent
with the notebook code behind it.

With Lens, you point at a result instead of describing it. Select part of a
view, add a note such as "Why does Q3 dip?", and the agent receives your
selection. In Studio you can select a placed cell, a number on a page, a bar in
a chart that page code draws, or a figure inside a Typst PDF.

Each [selection](../reference/glossary.md#selection) carries two kinds of
evidence. Lens records what you pointed at. Studio adds where it came from:
the cell that computed it, the value it shows, and the place in the view
project that shows it. With both, the agent can tell whether a request belongs
in the notebook or in the view.

<llm-exclude>

<StudioLensTrace />

</llm-exclude>

## Set up Lens

Lens runs in the notebook's Python environment. For a notebook opened with
`--sandbox`, add it to the script's dependencies, then stop the running edit
command and start it again:

```console
uv add --script analysis.py "marimo-studio[lens]"
uvx --with marimo-studio marimo edit analysis.py --sandbox --watch
```

In a uv project, add it to the project and restart the notebook:

```console
uv add "marimo-studio[lens]"
```

In another activated virtual environment, install it there instead:

```console
uv pip install "marimo-studio[lens]"
```

When the notebook creates no Lens of its own, marimo
mounts one, and Notebook and Preview each show a Lens dock, the panel that
lists your selections. Both docks share
one Lens, so a selection made in a view reaches the same agent as a selection
made in the notebook.

Lens hands selections to a code-mode agent, an agent that runs Python in the
live notebook, such as one connected through
[`marimo pair`](https://marimo.io/pair) or marimo's AI sidebar.
[Author with a coding agent](coding-agents.md) connects one. Then select a
result, add a note, and ask:

> Use Lens to address my current selection in this Studio view.

## What a selection traces to

Every part of a view is a [Lens target](../reference/glossary.md#lens-target).
What the selection traces to depends on how the view shows the part:

| You select                    | In the view source                                        | The selection traces to                                                                                   |
| ----------------------------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| A placed cell                 | `<marimo-cell name="region_control">`                     | The cell `region_control` and the cells upstream of it                                                    |
| An output                     | `<marimo-output value="quarterly_chart">`                 | The variable `quarterly_chart` and the cell that defines it                                               |
| A value                       | `<strong mo-value="summary.orders">`                      | The value selector `summary.orders` and the cell `summary`                                                |
| A chart that page code draws  | An element with `data-marimo-lens-inputs`                 | The hosts it lists, with their selectors and cells                                                        |
| Part of a PDF or a video      | A [render region](../reference/glossary.md#render-region) | The value selector, such as `report.rows[2].orders`, its cell, and the source line, such as `main.typ:41` |
| Text or layout with no inputs | Any element inside `#app-shell`                           | The view page, with no notebook cells                                                                     |

Lens follows marimo's
[dataflow graph](https://docs.marimo.io/guides/editor_features/dataflow/) from
the producing cell to the cells and control values upstream of it, and an
image of the selected target joins the selection when the browser can capture
one. The [Lens documentation](https://marimo-team.github.io/marimo-lens/how-lens-works)
lists everything an agent receives.

## How Studio connects a selection to the notebook

Lens on its own knows notebook outputs by the cell that renders them. A view
shows results outside the notebook, so Studio supplies the link for each kind
of target:

- **Hosts.** Studio resolves every host to its target and producing cell when
  the page opens, and marks the host with both. Selecting a host reads those
  marks, so the view source carries no extra attributes.
- **Page code.** Studio cannot follow JavaScript from a value to the element
  it draws. A region that page code draws lists its inputs with
  `data-marimo-lens-inputs`, and the selection takes their cells.
- **Rendered files.** A PDF or a video is a picture of results. When the
  provider renders the file, it reports a render region for each placed
  result: a rectangle on a page, an image, or a span of video frames, with the
  results it shows. A provider can also report the line that placed each
  region. Without one, the selection names the line where the source reads the
  region's first result. The Typst and LaTeX providers report that read line,
  such as the `marimo_value("report")` call, which can sit above the code that
  draws the result. Studio lays an invisible box over each region, and Lens
  selects the boxes.
- **Authored content.** Headings, prose, and layout read no results. Lens
  selects them by their nearest section or card, and the selection names the
  view page with no notebook cells, so the agent edits the view. An authored
  region can also name its source file, as
  [Mark authored regions](#mark-authored-regions) shows.

## Make page code selectable

`<marimo-cell>`, `<marimo-output>`, and `mo-value` hosts are selectable
without extra markup. A chart or component that page code draws stays
connected through hidden hosts. List them on the element that shows the
drawing:

```html
<div hidden>
  <span id="rows-data" hidden mo-value="rows"></span>
  <span id="summary-data" hidden mo-value="summary.total"></span>
</div>
<section data-marimo-lens-inputs="rows-data summary-data">
  <!-- JavaScript renders the chart here. -->
</section>
```

Lens selects the parent of a hidden host as that host's target, as in
[Select one metric](#select-one-metric). Group hosts that only feed page code
in a hidden container. A hidden host placed directly in `#app-shell` makes the
whole page one target.

`data-marimo-lens-inputs` lists host IDs in the same document, separated by
spaces, and declares the region's complete set of notebook inputs. Lens reads
each host's resolved selector and producing cell. A reference can also point to
a `<marimo-output>` or `<marimo-cell>` host. A missing, duplicate, or unbound
reference makes the region unavailable, and a reference cannot pass through
another annotated region.

Update the references when the drawing's inputs change, including transformed
inputs and portals. Set `aria-busy="true"` while the drawing renders and clear
it when it finishes. A chart drawn on a canvas is one target unless its
renderer adds finer DOM targets.

### Select one metric

Give each metric its own hidden host, so a selection names its exact field:

```html
<article class="metric">
  <span hidden mo-value="summary.events"></span>
  <span>Events</span>
  <strong><!-- JavaScript formats the value here. --></strong>
</article>
```

Use a visible `mo-value` when its plain text needs no formatting. For a value
without a JSON form, reference a hidden `<marimo-output>` host through
`data-marimo-lens-inputs`.

A selector that page state computes, such as one row of a table, needs the
Python or Browser runtime, because a
[prepared export](../reference/glossary.md#prepared-export) needs a fixed set
of targets. In a prepared view, place the whole collection with one selector
and reference that host from each row, with the row in
`data-marimo-lens-detail`.

### Label a selection

While you select, Lens outlines the target and labels its edge with the cell
or variable name Studio resolved. Set a label and a detail line when a region
needs a clearer name:

```html
<section
  data-marimo-lens-inputs="rows-data summary-data"
  data-marimo-lens-label="Revenue forecast"
  data-marimo-lens-detail="Monthly revenue · selected region"
>
  <!-- Custom rendering -->
</section>
```

Labels change what Lens shows. The selection's notebook cells stay the same.

## Mark authored regions

Text and layout inside `#app-shell` are selectable. Lens groups a click into
the nearest section, card, figure, or block. Set the grouping selector on the
app shell:

```html
<main id="app-shell" data-marimo-lens-scope=".card, header, figure">
  <!-- Authored regions are selectable. -->
</main>
```

Give a region its own identity with `data-marimo-lens-target` and a stable
`id`, so Lens can reconnect feedback when a rebuild updates the page in place:

```html
<header
  id="intro"
  data-marimo-lens-target
  data-marimo-lens-label="Introduction"
  data-marimo-lens-render-source='{"path":"index.html"}'
>
  <h1>Regional outlook</h1>
</header>
```

`data-marimo-lens-render-source` names the file that holds the region. Add
`data-marimo-lens-inputs` when the region also shows notebook results.

A page with its own `<script>` elements reloads when a rebuild changes its
markup. Selections made before the reload stay open, and their targets show as
unavailable.

## Mark parts of a PDF

The Typst and LaTeX providers locate each figure and cell a document places,
so those parts are selectable without extra markup. Wrap text or table cells
built from values to make them selectable too:

::: code-group

```typst [Typst]
#import "marimo.typ": marimo_region, marimo_value

#marimo_region("summary.rooms", label: "Rooms in use")[
  Rooms in use: #marimo_value("summary.rooms", default: 0)
]
```

```latex [LaTeX]
Rooms in use: \marimoregion[Rooms in use]{summary.rooms}{\marimovalue{summary.rooms}}
```

:::

Each selector names a value the document reads, optionally narrowed with
`.field` and `[index]` steps, such as `rows[2].orders`. A region keeps its body
on one page, so mark the cells of a long table one by one. Views created
before regions existed need the current `marimo.typ` or `marimo.sty` from a
new view's starter.

Selecting the file outside its regions traces it to every result the render
reads, up to 64 of them. In a video, the boxes follow the playing time.
Preview runs rendered files in an isolated origin, so Lens captures no image of
a video frame. The selection keeps its cells, label, and source line.

A [view provider](view-providers.md) for another tool reports regions from
`render()`. [Locate parts of rendered files](../reference/provider-api.md#locate-parts-of-rendered-files)
defines the record.

## Put a Lens dock in a live view

Preview reuses the Lens that marimo mounts in the notebook. To give readers of
a view served by `marimo run` their own dock, create the Lens in the notebook:

```python
from marimo_lens import Lens
from marimo_studio import STUDIO_RESULT_SELECTOR

studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)
None
```

The final `None` keeps the cell's output empty. Place the Lens in the view:

```html
<marimo-output value="studio_lens"></marimo-output>
```

`STUDIO_RESULT_SELECTOR` matches hosts, elements with declared inputs, explicit
authored targets, and render regions. marimo skips its own Lens in a notebook that creates one, so
`studio_lens` is the notebook's only Lens.

[Notebook result projections](../reference/projections.md#lens-attributes)
lists every Lens attribute, and the
[Lens agent guide](https://marimo-team.github.io/marimo-lens/agents) covers how
an agent inspects, resolves, and reports on selections.
