---
title: Place notebook results in a view
description: Place cells, outputs, and values from a marimo notebook in a web page, a Quarto document, or a Typst or LaTeX PDF.
---

# Place notebook results in a view

A view places notebook [results](../reference/glossary.md#result) by name: a
[cell](../reference/glossary.md#cell), an
[output](../reference/glossary.md#output), or a
[value](../reference/glossary.md#value). Each format writes them in its own
syntax:

::: v-pre

| Result | Page                             | Quarto                                | Typst                           | LaTeX                        |
| ------ | -------------------------------- | ------------------------------------- | ------------------------------- | ---------------------------- |
| Cell   | `<marimo-cell name="filters">`   | `{{< marimo cell="filters" >}}`       | `#marimo_cell("filters")`       | `\marimocell{filters}`       |
| Output | `<marimo-output value="chart">`  | `{{< marimo output="chart" >}}`       | `#marimo_output("chart")`       | `\marimographics{chart}`     |
| Value  | `<span mo-value="totals.rooms">` | `{{< marimo value="totals.rooms" >}}` | `#marimo_value("totals.rooms")` | `\marimovalue{totals.rooms}` |

:::

On a [page](../reference/glossary.md#page), each result goes in a
[host](../reference/glossary.md#host), an element that Studio fills with the
result while the page is open. The built-in starters write the page as plain
HTML, React, Svelte, Reveal.js, or Notebook Kit source, and a
[view provider](view-providers.md) can build it from any other framework.
Write the hosts inside the page's
[app shell](../reference/glossary.md#app-shell), the `#app-shell` element, in
the markup of the view's framework. Quarto builds a page too, and Studio
supplies `#app-shell` for it. Typst and LaTeX compile a PDF, a
[render](../reference/glossary.md#render) that holds no controls, so their
source places images and values.

[How Studio works](../how-studio-works.md#hosts-receive-results-while-the-page-is-open)
shows what each host receives while the page is open, and
[Select results with Lens](lens.md) traces any placed result back to its cell.

## Name results in the notebook

A **cell** is named by its function name. Write `def sport_control(...)` in the
notebook file, or rename the cell in the editor.

An **output** or a **value** is named by a variable that a cell defines, and a
[value selector](../reference/glossary.md#value-selector) can step into it:

```text
summary.total
rows[0]
results["overview"]
```

Give an unnamed cell a [cell alias](../reference/glossary.md#cell-alias) when
renaming its function is not an option:

```console
uvx marimo-studio notebook bind summary --target analysis.py --cell 12
```

The alias belongs to the notebook, so every view can use it.

## Place a cell

```python
@app.cell
def sport_control(athletes, mo):
    sport = mo.ui.dropdown(
        options=athletes["sport"].unique().sort().to_list(),
        label="Sport",
    )
    sport
    return (sport,)
```

```html
<marimo-cell name="sport_control"></marimo-cell>
```

A page shows the cell as the notebook does, with its native controls, logs,
and errors. Changing the dropdown reruns the cells that depend on `sport`, and
every result on the page updates.

In a document, `marimo_cell()` and `\marimocell` place the image a cell shows,
such as the PNG of a matplotlib figure. A cell that shows a control, text, or
a table places nothing there, so read its value instead:
`#marimo_value("sport.value")`.

## Place an output

`marimo-output` renders one Python object with marimo's own renderer, even an
object that no cell displays:

```html
<marimo-output value="selected_roster"></marimo-output>
```

In a document, an output must have an image form. `marimo_output()` and
`\marimographics` draw a matplotlib figure or an Altair chart as a vector PDF
at the width the document places it at, so its labels print at the point size
the notebook set:

::: code-group

```typst [Typst]
#import "marimo.typ": marimo_output

#figure(marimo_output("occupancy_chart", width: 100%), caption: [Rooms in use.])
```

```latex [LaTeX]
\begin{figure}
  \marimographics[width=\linewidth]{occupancy_chart}
  \caption{Rooms in use.}
\end{figure}
```

:::

## Place a value

On a page, `mo-value` writes a number, text, or boolean into the element:

```html
<p>Rooms in use: <strong mo-value="summary.rooms"></strong></p>
```

Page code can also read the value and draw it however it likes. The host
exposes the current value as `host.marimoValue` and dispatches
`marimo-value-updated` whenever it changes:

```html
<span id="summary-data" hidden mo-value="summary"></span>
<output id="summary-total"></output>

<script type="module">
  const host = document.querySelector("#summary-data");
  const output = document.querySelector("#summary-total");

  const render = (value) => {
    output.value = value.total.toLocaleString();
  };

  host.addEventListener("marimo-value-updated", (event) => {
    render(event.detail.value);
  });

  if (host.marimoValue !== undefined) {
    render(host.marimoValue);
  }
</script>
```

Register the listener before reading `marimoValue`. `undefined` means the
value has not arrived yet, and JSON `null` is a real value. Listen for
`marimo-value-error` to show a local error state. React starters wrap these
events in a `useMarimoValue` hook, and Svelte starters in a
`use:observeMarimoValue` action.

A document reads a value while it renders:

::: code-group

```typst [Typst]
#import "marimo.typ": marimo_value

Rooms in use: #marimo_value("summary.rooms", default: 0)
```

```latex [LaTeX]
Rooms in use on \marimodate{summary.day}: \marimonum{summary.rooms}.
```

:::

### Tables in page code

An eager dataframe reaches page code as a
[Flechette](https://github.com/uwdata/flechette) `Table`. Studio sends it as
[Arrow IPC](https://arrow.apache.org/docs/format/Columnar.html#serialization-and-interprocess-communication-ipc),
a columnar binary format, and decodes it before it updates the host:

```js
const chartRows = table.select(["region", "revenue"]).toArray();
```

Treat the table as read-only. Keep it columnar while you select fields or pass
it to a column-oriented library, and call `toArray()` where a consumer needs
row objects. Materialize lazy or remote queries in the notebook before a view
reads them.

### Renders read JSON

Typst and LaTeX renders read each value in its JSON form:

| Notebook value                              | Render reads                                 |
| ------------------------------------------- | -------------------------------------------- |
| pandas, Polars, or PyArrow table            | A list of row objects keyed by column name   |
| `date`, `datetime`, `time`                  | ISO 8601 text, such as `2015-02-04T09:41:00` |
| NumPy number, `Decimal`, or `Enum` member   | Its number or value                          |
| NaN, or a missing table cell                | `null`                                       |
| A step through `None`, such as `peak.label` | `null`, while `peak` is `None`               |
| Dictionary, list, text, number, boolean     | The same value                               |

The Typst or LaTeX source formats what it reads. LaTeX has `\marimonum`,
`\marimodate`, and `\marimorows`, which repeats a table row for each row of a
dataframe. Typst uses its own functions. A null value falls back to the
source's default.

A value whose JSON form holds more than 100,000 values or 1,000,000 bytes fails
with `value-too-large`. Filter or aggregate large tables in the notebook first.
[Limits](../reference/limits.md#runtime-payloads) lists every bound.

## Choose results at runtime

React and Svelte providers find the targets a view uses while they build it.
Literal names and finite arrays work:

```tsx
export const Results = () => (
  <section>
    {["summary", "details"].map((name) => (
      <marimo-cell key={name} name={name} />
    ))}
  </section>
);
```

When page state can pick any notebook target, declare that on the host:

```tsx
<marimo-cell name={selectedName} data-marimo-allow="*" />
```

`data-marimo-allow="*"` lets that host request any target of the same kind.
Put it on the narrowest host that needs it. A computed name without it fails
provider inspection. A Prepared export needs finite targets and rejects wildcard hosts,
so export a view that picks targets at runtime with `--runtime wasm`.

## Check the names

Check that every name a view uses exists in the notebook, without running it:

```console
uvx marimo-studio validate dashboard --target analysis.py
```

Add `--level runtime` to run the notebook and check each result the view
reads. Runtime validation runs every cell, including its file, network, and
database access, so use it with notebooks you trust.

[Notebook result projections](../reference/projections.md) defines host
attributes, events, loading states, and limits.
